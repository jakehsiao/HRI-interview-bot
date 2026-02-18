# -*- coding: utf-8 -*-
import sys
import time
from naoqi import ALProxy

class NaoInterviewer:
    def __init__(self, ip, port=9559):
        self.ip = ip
        self.port = port
        
        # 初始化代理 (Proxies)
        try:
            self.tts = ALProxy("ALAnimatedSpeech", self.ip, self.port)
            self.asr = ALProxy("ALSpeechRecognition", self.ip, self.port)
            self.mem = ALProxy("ALMemory", self.ip, self.port)
            self.motion = ALProxy("ALMotion", self.ip, self.port)
            self.posture = ALProxy("ALRobotPosture", self.ip, self.port)
        except Exception as e:
            print "Error connecting to NAO: ", e
            sys.exit(1)

    def start_interview(self):
        # 1. 唤醒并站立
        print "Waking up..."
        self.motion.wakeUp()
        self.posture.goToPosture("Stand", 0.5)

        # 设置语音识别参数
        self.asr.setLanguage("English")
        # 这里的词汇表包含了我们需要用到的关键词
        vocabulary = ["yes", "no", "finished"]
        
        # 停止之前的识别（防止冲突）
        try:
            self.asr.unsubscribe("InterviewerApp")
        except:
            pass
            
        self.asr.setVocabulary(vocabulary, False)

        # --- 第一阶段: 问候与询问 ---
        # ^start(...) 是让机器人做特定动作的指令，这里使用BodyTalk让它说话时挥手
        self.tts.say("^start(animations/Stand/Gestures/Hey_1) Hello, I am your interviewer, are you finding for job?")
        
        # 听取答案
        answer = self.listen_for_keywords(["yes", "no"])
        
        if answer == "no":
            self.end_process()
            return
        elif answer == "yes":
            self.phase_two()
        else:
            # 如果没听清，默认进入结束或重试，这里按逻辑进入结束
            print "Timeout or unrecognized, ending."
            self.end_process()

    def phase_two(self):
        # --- 第二阶段: 自我介绍 ---
        self.tts.say("^start(animations/Stand/Gestures/Explain_1) Okay, Welcome to the interview, first please introduce yourself to me. When you finish your answer, say Over.")
        
        # 这里机器人会一直安静等待，直到听到 "Finished"
        print "Listening for 'Finished'..."
        self.listen_for_keywords(["finished", "over"], timeout=60) # 给用户60秒时间介绍

        # --- 第三阶段: 询问优势 ---
        self.tts.say("^start(animations/Stand/Gestures/Ask_1) Good, so what are your greatest strengths?")

        # 这里机器人会一直安静等待，直到听到 "Finished"
        print "Listening for 'Finished'..."
        self.listen_for_keywords(["finished", "over"], timeout=60) # 给用户60秒时间介绍
        
        # 进入结束流程
        self.end_process()

    def end_process(self):
        # --- 结束流程 ---
        self.tts.say("^start(animations/Stand/Gestures/BowShort_1) Thank you for coming in today, have a nice day")
        # 休息（放松关节）
        self.motion.rest()
        # 停止识别引擎
        try:
            self.asr.unsubscribe("InterviewerApp")
        except:
            pass
        print "Interview ended."

    def listen_for_keywords(self, target_words, timeout=20):
        """
        监听特定的关键词。
        target_words: 列表，如 ["yes", "no"]
        timeout: 超时时间（秒）
        """
        self.asr.subscribe("InterviewerApp")
        self.mem.insertData("WordRecognized", "") # 清空缓存
        
        start_time = time.time()
        detected_word = None
        
        while True:
            # 检查超时
            if time.time() - start_time > timeout:
                break
                
            # 从内存中获取识别到的词 [word, confidence]
            data = self.mem.getData("WordRecognized")
            
            if data and isinstance(data, list) and len(data) >= 2:
                word = data[0]
                confidence = data[1]
                
                # NAO的识别阈值通常设为 0.4 左右
                if confidence > 0.4 and word in target_words:
                    detected_word = word
                    break
            
            time.sleep(0.1)
            
        self.asr.unsubscribe("InterviewerApp")
        return detected_word

if __name__ == "__main__":
    # 默认 IP，稍后我会教你如何修改或传参
    # 如果你在本地运行，请将下面的 IP 改为机器人的实际 IP
    ROBOT_IP = "127.0.0.1" 
    
    if len(sys.argv) > 1:
        ROBOT_IP = sys.argv[1]
    
    app = NaoInterviewer(ROBOT_IP)
    app.start_interview()