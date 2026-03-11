# -*- coding: utf-8 -*-
import sys
import time
import random
from naoqi import ALProxy
import urllib2
import json

# --- 全局配置常量 ---
ROBOT_IP = "127.0.0.1"
PORT = 9559

# 语音与静默检测参数
GLOBAL_SENSITIVITY = 0.9       # 声音检测灵敏度
SILENCE_THRESHOLD = 0.3        # 判定为“停顿”的秒数
SILENCE_TIMEOUT = 3.5          # 判定为“说话结束”的秒数
FEEDBACK_COOLDOWN = 3.5        # 两次反馈之间的最小间隔（秒）

# 识别配置
ASR_CONFIDENCE_THRESHOLD = 0.4 # 语音识别置信度阈值
LISTEN_TIMEOUT = 20.0          # 关键词等待超时

class NaoInterviewer:
    def __init__(self, ip, port=PORT):
        self.ip = ip
        self.port = port
        self.last_feedback_time = 0
        self.word_id = 0
        
        try:
            # 初始化代理
            self.tts = ALProxy("ALAnimatedSpeech", self.ip, self.port)
            self.tts2 = ALProxy("ALTextToSpeech", self.ip, self.port)
            self.tts2.setLanguage("English")
            self.asr = ALProxy("ALSpeechRecognition", self.ip, self.port)
            self.mem = ALProxy("ALMemory", self.ip, self.port)
            self.motion = ALProxy("ALMotion", self.ip, self.port)
            self.posture = ALProxy("ALRobotPosture", self.ip, self.port)
            self.sound_detect = ALProxy("ALSoundDetection", self.ip, self.port)
            self.audio = ALProxy("ALAudioDevice", self.ip, self.port)
            self.life = ALProxy("ALAutonomousLife", self.ip, self.port)

            # 音频与系统状态初始化
            self.audio.muteAudioOut(False)
            self.audio.setOutputVolume(80)
            
            if self.life.getState() != "disabled":
                self.life.setState("disabled")
            
            print "Nao initialized and ready."

        except Exception as e:
            print "Error connecting to NAO: ", e
            sys.exit(1)

    def start_interview(self):
        """ 启动面试流程 """
        self.motion.wakeUp()
        self.posture.goToPosture("Stand", 0.5)

        self.asr.setLanguage("English")
        vocabulary = ["yes", "no"]
        
        try:
            self.asr.unsubscribe("InterviewerApp")
        except:
            pass
        self.asr.setVocabulary(vocabulary, False)

        # 阶段一：开场
        self.tts.say("^start(animations/Stand/Gestures/Hey_1) Hello, I am your interviewer. Are you looking for a job?")
        
        answer = self.listen_for_keywords(["yes", "no"])
        
        if answer == "yes":
            self.phase_two()
        else:
            print "Interview declined or timeout."
            self.end_process()

    def phase_two(self):
        """ 阶段二：自我介绍与优势询问 """
        # 自我介绍环节
        self.tts.say("^start(animations/Stand/Gestures/Explain_1) Great. First, please introduce yourself to me.")
        self.listen_for_silence()

        # 优势询问环节
        self.tts.say("^start(animations/Stand/Gestures/Ask_1) Good, it's clear that you're a strong candidate. so tell me a project you are working on recently, what is the project? What have you done in it?")
        self.listen_for_silence()
        
        self.end_process()

    def listen_for_silence(self):
        """ 核心监听逻辑：使用全局常量控制静默判定 """
        self.sound_detect.setParameter("Sensitivity", GLOBAL_SENSITIVITY)
        self.sound_detect.subscribe("InterviewerApp_Sound")
        
        last_sound_time = time.time()
        is_speaking = False 
        last_data = self.mem.getData("SoundDetected")
        
        print " > Listening..."

        while True:
            current_data = self.mem.getData("SoundDetected")
            current_time = time.time()
            
            if current_data != last_data:
                # 检测到声音
                last_sound_time = current_time
                last_data = current_data
                if not is_speaking:
                    is_speaking = True
                    print "Status: Speaking"
            else:
                # 静默中
                silence_duration = current_time - last_sound_time
                
                # 判定为短暂停顿，触发随机反馈
                if is_speaking and silence_duration > SILENCE_THRESHOLD:
                    is_speaking = False
                    if current_time - self.last_feedback_time > FEEDBACK_COOLDOWN:
                        self.trigger_feedback()
                        # print "Current time:", current_time
                        # print "Last feedback:", self.last_feedback_time
                        self.last_feedback_time = current_time
                
                # 判定为完全结束
                if silence_duration > SILENCE_TIMEOUT:
                    print "Status: Finished"
                    break
            
            time.sleep(0.1)
        
        try:
            self.sound_detect.unsubscribe("InterviewerApp_Sound")
        except:
            pass

    def trigger_feedback(self):
        """ 随机点头并给出口头反馈 """
        phrases = ["Well", "Aha", "Yeah", "I Know", "Oh", "Tell me more", "Good", "Oh Yeah", "Emmm"]
        chosen_phrase = random.choice(phrases)
        print "Robot feedback: " + chosen_phrase
        
        # 使用 post.say 以免阻塞声音监听循环
        self.tts.post.say("^start(animations/Stand/Gestures/Yes_1) " + chosen_phrase)

    def listen_for_keywords(self, target_words):
        """ 关键词识别逻辑 """
        self.asr.subscribe("InterviewerApp")
        self.mem.insertData("WordRecognized", "")
        start_time = time.time()
        detected_word = None

        while (time.time() - start_time) < LISTEN_TIMEOUT:
            data = self.mem.getData("WordRecognized")
            if data and isinstance(data, list) and len(data) >= 2:
                word = data[0]
                confidence = data[1]
                if confidence > ASR_CONFIDENCE_THRESHOLD and word in target_words:
                    detected_word = word
                    break
            time.sleep(0.1)

        self.asr.unsubscribe("InterviewerApp")
        return detected_word
    
    def read_feedback(self):
        feedback_text = ""
        try:
            print "Fetching feedback from LLM API..."
            # 使用 urllib2 发起 GET 请求，设置严格的 2 秒超时
            response = urllib2.urlopen("http://127.0.0.1:3005/get_feedback", timeout=2.0)
            result = json.loads(response.read())
            
            # 判断返回值状态和内容
            if result.get("status") == "success" and result.get("feedback"):
                # 将 unicode 转换为普通 string，防止 NAO 的 TTS 报错
                feedback_text = str(result.get("feedback"))
                print "Success: Feedback received."
            else:
                print "Warning: API returned empty or unsuccessful status."
                
        except urllib2.URLError as e:
            print "API Timeout or Connection Refused: ", e
        except Exception as e:
            print "Unexpected Error parsing feedback: ", e

        # 如果报错、超时或结果为空，给定一个兜底的默认反馈
        if not feedback_text:
            fallbacks = [
                "Overall, you presented your ideas clearly and showed great confidence during our conversation today.",
                "I am impressed by your professional attitude. You addressed the core of my questions with a very structured approach.",
                "You have a strong way of expressing your thoughts. Your background seems to align well with many of our requirements.",
                "Thank you for sharing those insights. Your communication skills are solid, and you maintain a good pace throughout the interview.",
                "Based on what you've shared, you clearly have a good grasp of your field and can articulate your value effectively."
            ]
            # 随机挑选一个
            feedback_text = random.choice(fallbacks)
        # 让 NAO 读出反馈内容
        self.tts.say(feedback_text)

    def end_process(self):
        """ 结束面试给出反馈 并休息 """
        # txt = "AAA"
        # while txt != "":
        #     # txt = raw_input("Enter the text:").decode("utf-8").encode("utf-8")
        #     txt = raw_input("Enter the text:")
        #     print txt
        #     self.tts.say(txt)
        #     self.tts.say(txt)
        self.tts.say("^start(animations/Stand/Gestures/Explain_1) Thank you for your interview, here is a detailed feedback on what I think about your answers.")
        self.tts.say("^start(animations/Stand/Gestures/Explain_1) For the first question.")
        self.read_feedback()
        self.tts.say("^start(animations/Stand/Gestures/Explain_1) For the second question.")
        self.read_feedback()
        self.tts.say("^start(animations/Stand/Gestures/BowShort_1) Thank you for your interview, have a nice day!")
        self.motion.rest()
        print "Interview ended."

if __name__ == "__main__":
    app = NaoInterviewer(ROBOT_IP)
    app.start_interview()