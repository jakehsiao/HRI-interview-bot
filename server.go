package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"
)

// ==========================================
// 1. 全局数据结构 (保持不变)
// ==========================================

type FeedbackQueue struct {
	mu    sync.Mutex
	items []string
}

func (q *FeedbackQueue) Push(item string) {
	q.mu.Lock()
	defer q.mu.Unlock()
	q.items = append(q.items, item)
}

func (q *FeedbackQueue) Pop() (string, bool) {
	q.mu.Lock()
	defer q.mu.Unlock()
	if len(q.items) == 0 {
		return "", false
	}
	item := q.items[0]
	q.items = q.items[1:]
	return item, true
}

type DeepgramRESTResponse struct {
	Results struct {
		Channels []struct {
			Alternatives []struct {
				Transcript string `json:"transcript"`
			} `json:"alternatives"`
		} `json:"channels"`
	} `json:"results"`
}

// ==========================================
// 2. 工具函数：读取本地 TXT 文件中的 Key
// ==========================================

func readKeyFromFile(filename string) string {
	content, err := os.ReadFile(filename)
	if err != nil {
		fmt.Printf("❌ 错误：无法读取文件 %s，请检查文件是否存在。\n", filename)
		os.Exit(1)
	}
	// 去掉可能存在的换行符和空格
	key := strings.TrimSpace(string(content))
	if key == "" {
		fmt.Printf("⚠️ 警告：文件 %s 内容为空。\n", filename)
	}
	return key
}

// ==========================================
// 3. 核心工作线程
// ==========================================

// 线程 A: 控制器 (监听回车 -> 录音 -> 调 Deepgram -> 发给大模型)
func audioControllerWorker(llmTaskChan chan<- string, dgKey string) {
	reader := bufio.NewReader(os.Stdin)
	audioFile := "temp_interview.wav"

	for {
		fmt.Println("\n==================================")
		fmt.Print("👉 请按下 [Enter] 键开始录音...")
		reader.ReadString('\n')

		os.Remove(audioFile)

		fmt.Print("🎙️ [录音中...] 正在录音。说完后请再次按下 [Enter] 键结束...")
		
		// 启动后台录音进程 (需要安装 sox)
		cmd := exec.Command("rec", "-q", "-c", "1", "-r", "16000", audioFile)
		err := cmd.Start()
		if err != nil {
			fmt.Printf("\n❌ 启动录音失败: %v\n", err)
			continue
		}

		reader.ReadString('\n') // 再次回车结束
		
		if cmd.Process != nil {
			cmd.Process.Kill()
			cmd.Wait()
		}
		
		fmt.Println("\n✅ [录音结束] 正在识别音频...")

		audioData, err := os.ReadFile(audioFile)
		if err != nil {
			fmt.Println("❌ 读取音频失败:", err)
			continue
		}

		transcript := callDeepgramREST(audioData, dgKey)
		if transcript == "" {
			fmt.Println("⚠️ 未检测到有效语音内容。")
			continue
		}

		fmt.Printf("🗣️ [识别结果]: %s\n", transcript)
		llmTaskChan <- transcript
	}
}

func callDeepgramREST(audioData []byte, apiKey string) string {
	urlStr := "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true"
	req, _ := http.NewRequest("POST", urlStr, bytes.NewReader(audioData))
	req.Header.Set("Authorization", "Token "+apiKey)
	req.Header.Set("Content-Type", "audio/wav")

	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return ""
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	var dgResp DeepgramRESTResponse
	json.Unmarshal(body, &dgResp)

	if len(dgResp.Results.Channels) > 0 && len(dgResp.Results.Channels[0].Alternatives) > 0 {
		return dgResp.Results.Channels[0].Alternatives[0].Transcript
	}
	return ""
}

// 线程 B: 硅基流动大模型调用
func llmWorker(taskChan <-chan string, queue *FeedbackQueue, sfKey string) {
	url := "https://api.siliconflow.cn/v1/chat/completions"
	systemPrompt := `Role: Efficient Interview Coach.
Task: Evaluate the transcript in exactly 3 short sentences.
Rules:
1. NO thinking process. NO preamble. NO bolding.
2. Sentence 1: Summarize the answer.
3. Sentence 2: One specific strength. Start with "What have you done well is".
4. Sentence 3: One actionable improvement. Start with "However".
Constraint: Total response must be under 70 words. Respond ONLY with the 3 sentences.`

	for text := range taskChan {
		payload := map[string]interface{}{
			"model": "deepseek-ai/DeepSeek-V3",
			"messages": []map[string]string{
				{"role": "system", "content": systemPrompt},
				{"role": "user", "content": text},
			},
			"stream": false,
		}
		jsonData, _ := json.Marshal(payload)

		req, _ := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
		req.Header.Set("Authorization", "Bearer "+sfKey)
		req.Header.Set("Content-Type", "application/json")

		client := &http.Client{Timeout: 30 * time.Second}
		resp, err := client.Do(req)
		if err != nil {
			fmt.Printf("<<< [LLM 错误]: %v\n", err)
			continue
		}

		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()

		var result map[string]interface{}
		json.Unmarshal(body, &result)

		if choices, ok := result["choices"].([]interface{}); ok && len(choices) > 0 {
			message := choices[0].(map[string]interface{})["message"].(map[string]interface{})
			feedback := message["content"].(string)
			fmt.Printf("<<< [LLM 反馈已入队]:\n%s\n", feedback)
			queue.Push(feedback)
		}
	}
}

// 线程 C: REST API 服务
func apiServerWorker(queue *FeedbackQueue) {
	http.HandleFunc("/get_feedback", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		feedback, ok := queue.Pop()
		if !ok {
			w.Write([]byte(`{"status": "empty"}`))
			return
		}
		json.NewEncoder(w).Encode(map[string]string{"status": "success", "feedback": feedback})
	})
	fmt.Println("[API 服务] 监听端口 :3005")
	http.ListenAndServe(":3005", nil)
}

// ==========================================
// 4. Main 启动
// ==========================================

func main() {
	// 启动前先读 Key
	dgKey := readKeyFromFile("deepgram_key.txt")
	sfKey := readKeyFromFile("siliconflow_key.txt")

	llmTaskChan := make(chan string, 10)
	feedbackQueue := &FeedbackQueue{}

	go audioControllerWorker(llmTaskChan, dgKey)
	go llmWorker(llmTaskChan, feedbackQueue, sfKey)
	go apiServerWorker(feedbackQueue)

	select {}
}