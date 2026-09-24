# Codex 사용량 위젯

Windows 바탕화면 아래쪽에 사로롱 캐릭터와 Codex 사용량을 띄우는 위젯입니다.

## 사용 방법

1. `Codex 사용량 캐릭터.exe`를 더블클릭합니다.
2. Codex 앱에 ChatGPT 계정으로 로그인되어 있어야 합니다.
3. 10초마다 5시간 및 주간 사용량을 새로 읽습니다.

위젯을 드래그하면 원하는 위치로 옮길 수 있습니다. 우클릭 메뉴의 `간소화`를 켜면 캐릭터는 오른쪽에 두고, 왼쪽에 사용량 이름·남은 퍼센트·초기화 시각만 말풍선 없이 표시합니다. 설정은 다음 실행에도 유지됩니다. 모니터 아래쪽에 붙이기, 투명도, 새로고침, 종료도 우클릭 메뉴에서 선택할 수 있습니다.

## 소스에서 실행

```powershell
.\.venv\Scripts\python.exe .\codex_usage_widget.py
```

Python 실행에는 Tkinter와 Codex CLI가 필요합니다. 실행 파일을 다시 만들려면 캐릭터 이미지를 포함해 다음 명령을 사용합니다.

```powershell
.\.venv\Scripts\pyinstaller.exe --onefile --windowed --add-data ".\assets\codex_mascot.png;assets" --name "Codex 사용량 캐릭터" .\codex_usage_widget.py
```

캐릭터 이미지는 `assets/codex_mascot.png`입니다. 위젯은 Codex app-server의 `account/rateLimits/read` 요청을 사용해 현재 계정의 사용량과 초기화 시각을 읽습니다.

## 구성

- `Codex 사용량 캐릭터.exe`: Python 설치 없이 실행할 수 있는 Windows 실행 파일
- `codex_usage_widget.py`: 위젯 소스
- `assets/codex_mascot.png`: 배경이 투명한 캐릭터 이미지

설정 파일은 `%LOCALAPPDATA%\CodexUsageWidget\settings.json`에 저장됩니다.
