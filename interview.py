# -*- coding: utf-8 -*-
import sys
import time
from naoqi import ALProxy

SENSITIVITY = 0.8
SILENCE_THRESHOLD = 0.5
SILENCE_TIMEOUT = 3.0

ROBOT_IP = "127.0.0.1" 
PORT = 9559

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
            # [新增] 声音检测模块，用于判断音量
            self.sound_detect = ALProxy("ALSoundDetection", self.ip, self.port)

            # --- [新增/修改部分：音量与系统控制] ---
            self.audio = ALProxy("ALAudioDevice", self.ip, self.port)
            self.life = ALProxy("ALAutonomousLife", self.ip, self.port)

            # 1. 强制取消静音 (对应你之前在 bash 遇到的 Bool 报错问题)
            self.audio.muteAudioOut(False)
            
            # 2. 设置音量为 80
            self.audio.setOutputVolume(80)
            
            print "Audio initialized: Mute=False, Volume=80"
            
            # 3. 尝试关闭自主生活模式 (防止 ASR 报错)
            if self.life.getState() != "disabled":
                self.life.setState("disabled")
                print "Autonomous Life disabled."

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
        vocabulary = ["yes", "no"]
        
        try:
            self.asr.unsubscribe("InterviewerApp")
        except:
            pass

        # try:
        #     self.asr.pause(True)
        # except:
        #     print "ASR already paused."
            
        self.asr.setVocabulary(vocabulary, False)

        # --- 第一阶段: 问候与询问 (保持原有的关键词识别，因为Yes/No很短) ---
        self.tts.say("^start(animations/Stand/Gestures/Hey_1) Hello, I am your interviewer, are you finding for job?")
        
        answer = self.listen_for_keywords(["yes", "no"])
        
        if answer == "no":
            self.end_process()
            return
        elif answer == "yes":
            self.phase_two()
        else:
            print "Timeout or unrecognized, ending."
            self.end_process()

    def phase_two(self):
        # --- 第二阶段: 自我介绍 (改为自动静默检测) ---
        self.tts.say("^start(animations/Stand/Gestures/Explain_1) Okay, Welcome to the interview, first please introduce yourself to me.")
        
        print "Listening for speech (Auto silence detection)..."
        # 调用新的监听函数，设定灵敏度0.3 (0-1之间，越大越灵敏)，静默超时2秒
        self.listen_for_silence(sensitivity=0.5, silence_timeout=2.0)

        # --- 第三阶段: 询问优势 (改为自动静默检测) ---
        self.tts.say("^start(animations/Stand/Gestures/Ask_1) Good, so what are your greatest strengths?")

        print "Listening for speech (Auto silence detection)..."
        self.listen_for_silence(sensitivity=0.3, silence_timeout=2.0)
        
        # 进入结束流程
        self.end_process()

    def listen_for_silence(self, sensitivity=0.3, silence_timeout=2.0):
        """
        根据音量阈值自动判断用户是否说完。
        sensitivity: 0.0 到 1.0，阈值。0.3 通常适合安静的办公室环境。
        silence_timeout: 持续停顿多少秒视为结束。
        """
        # 1. 设置声音检测的灵敏度 (相当于音量阈值)
        self.sound_detect.setParameter("Sensitivity", SENSITIVITY)
        self.sound_detect.subscribe("InterviewerApp_Sound")
        
        # 记录状态
        last_sound_time = time.time()
        is_speaking = False  # 标记当前是否正在说话状态
        
        # 获取初始状态，用于对比
        last_data = self.mem.getData("SoundDetected")
        
        print "  > Waiting for user to speak..."

        while True:
            # 获取 SoundDetected 数据
            # 数据结构通常包含 [时间戳, 类型, 信心度...]，如果数据变化了，说明检测到了声音
            current_data = self.mem.getData("SoundDetected")
            
            # 判断是否有新的声音事件 (即用户在说话)
            # 注意：SoundDetected 在安静时不会更新，或者更新为低信心度
            # 这里我们简单通过对比数据变化来判断是否有达到阈值的响声
            if current_data != last_data:
                # === 检测到声音 ===
                last_sound_time = time.time()
                last_data = current_data
                
                if not is_speaking:
                    is_speaking = True
                    # 这里可以选择打印 "Speaking..." 或者保持安静
                    print "Speaking..."
            
            else:
                # === 没有检测到新声音 (静默中) ===
                current_time = time.time()
                silence_duration = current_time - last_sound_time
                
                # 逻辑1: 检测到停顿 (用户之前在说话，现在停了，且停顿超过了0.5秒防抖)
                if is_speaking and silence_duration > SILENCE_THRESHOLD:
                    print "Paused"
                    is_speaking = False # 状态转为暂停
                
                # 逻辑2: 停顿时间超过设定阈值 (如2秒) -> 结束
                # 注意：如果用户从未说话，也会在这里超时，这符合面试逻辑（用户不说话就跳过）
                if silence_duration > SILENCE_TIMEOUT:
                    print "Finished"
                    break
            
            time.sleep(0.1)
        
        # 退出前取消订阅
        try:
            self.sound_detect.unsubscribe("InterviewerApp_Sound")
        except:
            pass

    def end_process(self):
        # --- 结束流程 ---
        self.tts.say("^start(animations/Stand/Gestures/BowShort_1) Thank you for coming in today, have a nice day")
        self.motion.rest()
        try:
            self.asr.unsubscribe("InterviewerApp")
        except:
            pass
        print "Interview ended."

    def listen_for_keywords(self, target_words, timeout=20):
        # ... (保持原有的关键词监听代码不变，用于第一阶段的Yes/No) ...
        self.asr.subscribe("InterviewerApp")
        self.mem.insertData("WordRecognized", "")
        start_time = time.time()
        detected_word = None
        while True:
            if time.time() - start_time > timeout:
                break
            data = self.mem.getData("WordRecognized")
            if data and isinstance(data, list) and len(data) >= 2:
                word = data[0]
                confidence = data[1]
                if confidence > 0.4 and word in target_words:
                    detected_word = word
                    break
            time.sleep(0.1)
        self.asr.unsubscribe("InterviewerApp")
        return detected_word

if __name__ == "__main__":
    app = NaoInterviewer(ROBOT_IP, PORT)
    app.start_interview()