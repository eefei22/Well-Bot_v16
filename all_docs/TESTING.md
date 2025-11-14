## TESTING

| No. | Test Case | Done |
| :---- | :---- | :---- |
| **Activities – SmallTalk Activity** |  |  |
| 1 | Test natural language conversation flow using DeepSeek LLM |  |
| 2 | Test personalized responses using stored user persona and facts |  |
| 3 | Verify conversation ends after reaching maximum turn limit |  |
| 4 | Test detection of termination phrases like “bye”, “stop talking” |  |
| 5 | Test silence nudge after inactivity timeout |  |
| 6 | Test final silence timeout leading to session termination |  |
| 7 | Verify context processor notification triggers after 4+ turnsr |  |
| 8 | Test multilingual conversation (English, Chinese, Bahasa Malay) |  |
| 9 | Test audio playback for start, end, and nudge prompts |  |
| 10 | Verify all messages and responses logged to database |  |
| **Activities – Journal Activity** |  |  |
| 11 | Test voice-to-text journaling |  |
| 12 | Check automatic paragraph finalization after pause |  |
| 13 | Test use of termination phrase to end journaling |  |
| 14 | Verify auto-save of journal to database |  |
| 15 | Test content validation (below min word count should fail) |  |
| 16 | Verify automatic title generation with timestamp |  |
| 17 | Confirm default mood assignment after entry |  |
| 18 | Placeholder test for future topic extraction |  |
| 19 | Test silence nudge during recording |  |
| 20 | Test auto-save after final silence timeout |  |
| 21 | Verify multilingual counting (English words, Chinese chars) |  |
| 22 | Test audio feedback prompts during journaling |  |
| **Activities – Gratitude Activity** |  |  |
| 23 | Test speech-to-text gratitude recording |  |
| 24 | Verify detection of completion phrases |  |
| 25 | Confirm saved gratitude note in database |  |
| 26 | Test seamless handoff to SmallTalk after recording |  |
| 27 | Verify gratitude note injected into SmallTalk context |  |
| 28 | Test silence nudge during recording |  |
| 29 | Test timeout handling for inactivity |  |
| 30 | Verify audio feedback playback |  |
| **Activities – Meditation Activity** |  |  |
| 31 | Test guided meditation audio playback |  |
| 32 | Verify termination phrases interrupt playback |  |
| 33 | Test Rhino intent detection during playback |  |
| 34 | Verify simultaneous playback and listening |  |
| 35 | Test detection of completed vs. interrupted sessions |  |
| 36 | Verify SmallTalk handoff with correct completion context |  |
| 37 | Test language-based meditation audio selection |  |
| 38 | Verify contextual SmallTalk prompts after meditation |  |
| **Activities – Spiritual Quote Activity** |  |  |
| 39 | Verify religion-aware quote retrieval |  |
| 40 | Test quote rotation (no repeats) |  |
| 41 | Test text-to-speech quote playback |  |
| 42 | Confirm quote marked as seen in database |  |
| 43 | Test handoff to SmallTalk with quote context |  |
| 44 | Verify quote injected into SmallTalk context |  |
| **Activities – Activity Suggestion Activity** |  |  |
| 45 | Test ranked activity suggestion retrieval |  |
| 46 | Verify default suggestions when no rankings exist |  |
| 47 | Test keyword matching for spoken activity intent |  |
| 48 | Verify routing to selected activity |  |
| 49 | Test conversation context preservation in handoff |  |
| 50 | Test silence nudge and timeout handling |  |
| 51 | Test multi-language names and descriptions |  |
| 52 | Verify audio feedback playback |  |
| **Core Components – Wake Word Detection** |  |  |
| 53 | Test custom wake word detection accuracy |  |
| 54 | Verify continuous background listening |  |
| 55 | Check microphone audio stream management |  |
| 56 | Verify callback triggered on wake word detection |  |
| 57 | Test proper Porcupine resource cleanup |  |
| **Core Components – Speech-to-Text** |  |  |
| 58 | Test real-time streaming transcription |  |
| 59 | Verify interim (partial) STT results displayed |  |
| 60 | Confirm final transcription accuracy |  |
| 61 | Test language switching for STT (en, cn, bm) |  |
| 62 | Verify STT timeout behavior |  |
| 63 | Test single vs. multi-utterance modes |  |
| **Core Components – Text-to-Speech** |  |  |
| 64 | Test real-time TTS streaming |  |
| 65 | Verify multi-language voice selection |  |
| 66 | Test audio format configuration |  |
| 67 | Confirm PCM stream playback works |  |
| **Core Components – Intent Recognition** |  |  |
| 68 | Test Rhino-based intent recognition |  |
| 69 | Verify context-based Rhino intent handling |  |
| 70 | Test keyword-based intent matching |  |
| 71 | Verify normalized matching on text input |  |
| 72 | Check confidence score reporting |  |
| **Core Components – Conversation Audio Manager** |  |  |
| 73 | Verify mic and playback coordination |  |
| 74 | Test TTS and file audio playback |  |
| 75 | Verify mic mutes during audio playback |  |
| 76 | Test silence nudge and final silence timeout |  |
| 77 | Check pre/post delay prevents false pickup |  |
| 78 | Verify resource cleanup after use |  |
| **Core Components – Conversation Session** |  |  |
| 79 | Test start/stop of session lifecycle |  |
| 80 | Verify turn counting limits |  |
| 81 | Confirm database conversation creation |  |
| 82 | Verify all messages logged |  |
| 83 | Test emoji removal from assistant messages |  |
| 84 | Check message language tracking |  |
| **Core Components – LLM Integration** |  |  |
| 85 | Test streaming chat token updates |  |
| 86 | Verify message history continuity |  |
| 87 | Test configurable system prompts |  |
| 88 | Verify context injection mid-session |  |
| 89 | Test error handling and recovery |  |
| **Core Components – User Context Injector** |  |  |
| 90 | Test database fetch of persona and facts |  |
| 91 | Verify local file fallback if DB unavailable |  |
| 92 | Check local caching of context |  |
| 93 | Verify system message injection |  |
| 94 | Test graceful degradation when context missing |  |
| **Core Components – Termination Phrase Detection** |  |  |
| 95 | Test normalized phrase matching |  |
| 96 | Verify multiple matching strategies |  |
| 97 | Check active state requirement behavior |  |
| 98 | Verify exception raised when termination detected |  |
| **Core Components – Keyword Intent Matcher** |  |  |
| 99 | Test language-specific intent loading |  |
| 100 | Verify text normalization |  |
| 101 | Test multiple matching strategies |  |
| 102 | Check confidence score output |  |
| **Core Components – Activity Logger** |  |  |
| 103 | Verify time-of-day context assignment |  |
| 104 | Test Malaysian timezone accuracy |  |
| 105 | Check query logic for filtering logs |  |
| **Core Components – Intervention Poller** |  |  |
| 106 | Test periodic polling intervals |  |
| 107 | Verify emotion log detection |  |
| 108 | Test cloud service integration for suggestions |  |
| 109 | Verify record updates in intervention\_record.json |  |
| 110 | Test timestamp tracking to prevent duplicates |  |
| 111 | Verify automatic start/stop behavior |  |
| **System Features – Orchestration** |  |  |
| 112 | Test state transitions (STARTING → LISTENING → etc.) |  |
| 113 | Verify intent routing to activities |  |
| 114 | Check wake word pipeline lifecycle management |  |
| 115 | Test cleanup between activities |  |
| 116 | Verify global error recovery |  |
| **System Features – Wake Word Pipeline** |  |  |
| 117 | Test continuous wake word detection |  |
| 118 | Verify STT session starts after wake word |  |
| 119 | Test intent classification accuracy |  |
| 120 | Verify silence nudge and timeout behavior |  |
| 121 | Test audio feedback and TTS responses |  |
| **System Features – Configuration Management** |  |  |
| 122 | Verify user-specific config loading |  |
| 123 | Test language preference resolution |  |
| 124 | Check config caching |  |
| 125 | Verify per-language config file loading |  |
| 126 | Test global config fallback |  |
| **System Features – Audio System** |  |  |
| 127 | Test multi-format (WAV) playback |  |
| 128 | Verify Windows PowerShell playback fallback |  |
| 129 | Test PyAudio playback |  |
| 130 | Check mic coordination during playback |  |
| 131 | Verify delay management for nudge audio |  |
| **System Features – Multi-language Support** |  |  |
| 132 | Test automatic language detection |  |
| 133 | Verify localized prompts |  |
| 134 | Check localized audio paths |  |
| 135 | Verify TTS and STT language matching |  |
| **Database Integration – User Management** |  |  |
| 136 | Test user authentication |  |
| 137 | Verify user profile retrieval |  |
| 138 | Test language preference save/load |  |
| 139 | Verify religion preference storage |  |
| **Database Integration – Conversation Management** |  |  |
| 140 | Test conversation record creation |  |
| 141 | Verify message storage |  |
| 142 | Check conversation ending flag |  |
| 143 | Test turn tracking accuracy |  |
| **Database Integration – Activity Logging** |  |  |
| 144 | Test activity start logging |  |
| 145 | Verify intervention logs |  |
| 146 | Verify emotion logs |  |
| 147 | Check duration tracking |  |
| **Database Integration – Journal Management** |  |  |
| 148 | Test journal entry storage |  |
| 149 | Verify journal retrieval |  |
| 150 | Test draft entry saving |  |
| 151 | Verify topic tracking |  |
| **Database Integration – Gratitude Management** |  |  |
| 152 | Test gratitude entry saving |  |
| 153 | Verify gratitude retrieval |  |
| **Database Integration – Quote Management** |  |  |
| 154 | Test religion-based quote fetching |  |
| 155 | Verify seen quote tracking |  |
| 156 | Check quote rotation behavior |  |
| **Database Integration – Context Bundle** |  |  |
| 157 | Verify persona summary storage |  |
| 158 | Test facts storage |  |
| 159 | Check version tracking |  |
| 160 | Verify local cache for offline access |  |
| **Database Integration – Emotional Logs** |  |  |
| 161 | Test emotion entry query |  |
| 162 | Verify timestamp filtering |  |
| 163 | Check emotion label tracking |  |
| **Configuration & Localization – Configuration Files** |  |  |
| 164 | Verify global config values |  |
| 165 | Check per-language config files |  |
| 166 | Test intent config files |  |
| 167 | Verify intervention record updates |  |
| 168 | Check user persona fallback file |  |
| **Configuration & Localization – Configurable Features** |  |  |
| 169 | Test timeout configurations |  |
| 170 | Verify audio setting configs |  |
| 171 | Test turn limit configuration |  |
| 172 | Verify language code settings |  |
| 173 | Check audio file path configs |  |
| 174 | Test localized prompts per activity |  |
| 175 | Verify termination phrase config |  |
| **Configuration & Localization – Localization Support** |  |  |
| 176 | Test multilingual operation (EN/CN/BM) |  |
| 177 | Verify localized audio files |  |
| 178 | Check translated prompts and activity names |  |
| 179 | Test cultural adaptation (religion-aware content) |  |
