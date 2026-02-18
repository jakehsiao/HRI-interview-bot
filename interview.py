# -*- coding: utf-8 -*-
import sys
import time
import random
from naoqi import ALProxy

# --- 全局配置常量 ---
ROBOT_IP = "127.0.0.1"
PORT = 9559

# 语音与静默检测参数
GLOBAL_SENSITIVITY = 0.8       # 声音检测灵敏度
SILENCE_THRESHOLD = 0.3        # 判定为“停顿”的秒数
SILENCE_TIMEOUT = 2.0          # 判定为“说话结束”的秒数
FEEDBACK_COOLDOWN = 1.5        # 两次反馈之间的最小间隔（秒）

# 识别配置
ASR_CONFIDENCE_THRESHOLD = 0.4 # 语音识别置信度阈值
LISTEN_TIMEOUT = 20.0          # 关键词等待超时

class NaoInterviewer:
    def __init__(self, ip, port=PORT):
        self.ip = ip
        self.port = port
        self.last_feedback_time = 0
        
        try:
            # 初始化代理
            self.tts = ALProxy("ALAnimatedSpeech", self.ip, self.port)
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
        self.tts.say("^start(animations/Stand/Gestures/Ask_1) Good, so what are your greatest strengths?")
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
        phrases = ["Well", "Okay", "Hmmm", "I Know"]
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

    def end_process(self):
        """ 结束面试并休息 """
        self.tts.say("^start(animations/Stand/Gestures/BowShort_1) Thank you for your time, have a nice day!")
        self.motion.rest()
        print "Interview ended."

if __name__ == "__main__":
    app = NaoInterviewer(ROBOT_IP)
    app.start_interview()