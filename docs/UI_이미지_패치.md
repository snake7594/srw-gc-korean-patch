# UI 이미지 한국어화

메뉴 글자는 단순 문자열이 아니라 `add00dat.bin`의 GX I4 아틀라스와
`SCR` 타일맵으로 구성되어 있습니다. 기존 방식처럼 공유 아틀라스 위에
글자를 덧그리면 한 타일을 함께 쓰는 다른 메뉴까지 오염될 수 있으므로,
각 `SCR`을 독립 이미지로 렌더링한 뒤 타일을 다시 묶습니다.

단, 정적 `SCR`이 참조하지 않는 타일을 빈 공간으로 간주하면 안 됩니다.
게임은 전투·동적 메뉴에서 일부 타일을 번호로 직접 선택합니다. v1.0.2부터는
원본 타일과 번호를 전부 보존하고, 한국어 타일을 아틀라스 뒤에 추가한 뒤
번역 대상 `SCR`만 새 번호를 가리키는 copy-on-write 방식을 사용합니다.

## 글꼴

- 글꼴: 나눔스퀘어 네오 cBd (`NanumSquareNeo-cBd.ttf`)
- SHA-256: `4749FA5691157CF56A59D297B45E88894A646846048018CD7A4117FFB2869767`
- 런타임 대사 글꼴과 UI 이미지 글꼴은 같은 파일을 사용합니다.

글꼴 파일은 저장소나 릴리스에 재배포하지 않습니다. 빌더는 사용자 글꼴
폴더 `%LOCALAPPDATA%\Microsoft\Windows\Fonts\NanumSquareNeo-cBd.ttf`를
기본값으로 사용하며, 다른 위치에 있는 같은 파일은 `--font`로 지정할 수
있습니다. 어느 경우든 해시가 다르면 작업을 중단합니다.

## 글자 크기 기준

v1.0.7까지는 `draw_fitted_text`가 **영문판 캔버스에 들어갈 때까지** 글꼴을
줄이는 방식이었습니다. 영문 라벨의 잉크 영역이 일본어 원본과 다르면 한국어가
그 비율을 그대로 물려받아, 한글이 일본어보다 크거나 작게 나왔습니다.

`tools/ui_text_fit.py`는 대신 **일본 정식판 라벨의 잉크 상자**를 측정해
- 잉크 높이를 같게 맞추고,
- 세로 중심을 같은 주사선에 놓으며,
- 가로는 SCR 헤더가 고정한 캔버스를 넘칠 때만 축소합니다.

일본판보다 커지는 후보는 같은 오차일 때 항상 탈락시키므로, 한글이 일본어보다
큰 라벨은 사실상 사라집니다. 일본판과 캔버스 높이가 다른 SCR(`891`, `897`)은
같은 그림이 아니므로 기존 캔버스 맞춤 동작을 유지합니다.

캔버스 폭이 일본판보다 좁은 라벨(영문 단어가 짧아 SCR이 작게 잡힌 경우)은
높이를 맞출 수 없어 여전히 작게 렌더링됩니다. SCR 헤더를 바꾸면 인덱스 보존
감사가 실패하므로 이 제약은 의도적으로 유지합니다.

## 처리 대상

- 대형 UI 아틀라스 `518`: SCR 399개 중 문자 381개 재작성, 비문자 18개 보존
- 소형 UI 아틀라스 10개: SCR 75개 중 문자 66개 재작성, 비문자 9개 보존
- 타이틀 메뉴 아틀라스 `3489`: 문자 5개 재작성, 선택 강조 이미지 5개 보존
- 로딩 이미지 SPR `3508`: `Now Loading...`을 `불러오는 중...`으로 재작성
- 원본 아틀라스 타일 11,872개와 비문자 `SCR` 32개를 원래 번호·바이트 그대로 보존

일본 정식판 표시 의미를 기준으로 번역했고, 영문판에서 의미가 달라진 항목도
일본어 원문에 맞춰 교정했습니다. 예를 들어 `UNIT LIST`로 잘못 옮겨진
`連続攻撃`은 `연속 공격`, `Ctr` 뒤에 잘못 들어간 `지휘`는 `반격`으로
고쳤습니다.

## 재구성 순서

아래 명령의 일본판·영문 참고 `add00dat.bin`은 사용자가 직접 준비해야 하며
저장소에는 포함되지 않습니다.

```powershell
python -X utf8 .\tools\repack_direct_scr_atlas.py `
  .\input\add00dat.bin .\build\add00_step1.bin `
  --translations .\data\ui_block518_ko.json `
  --japanese .\reference\japanese\add00dat.bin `
  --english .\reference\english\add00dat.bin `
  --bitmap 518 `
  --font "$env:LOCALAPPDATA\Microsoft\Windows\Fonts\NanumSquareNeo-cBd.ttf" `
  --report .\build\ui_block518_audit.json `
  --preview-dir .\build\ui_block518_preview

python -X utf8 .\tools\repack_small_ui_atlases.py `
  .\build\add00_step1.bin .\build\add00_visual_reference.bin `
  --japanese .\reference\japanese\add00dat.bin `
  --english .\reference\english\add00dat.bin `
  --mapping .\data\ui_small_and_title_ko.json `
  --font "$env:LOCALAPPDATA\Microsoft\Windows\Fonts\NanumSquareNeo-cBd.ttf" `
  --report .\build\ui_small_title_audit.json `
  --preview-dir .\build\ui_small_title_preview

python -X utf8 .\tools\repack_preserve_indices.py `
  .\input\add00dat.bin .\build\add00_visual_reference.bin `
  .\build\add00_safe_preloading.bin `
  --large-mapping .\data\ui_block518_ko.json `
  --small-mapping .\data\ui_small_and_title_ko.json `
  --font "$env:LOCALAPPDATA\Microsoft\Windows\Fonts\NanumSquareNeo-cBd.ttf" `
  --report .\build\ui_preserved_index_audit.json `
  --preview-dir .\build\ui_preserved_index_preview

python -X utf8 .\tools\patch_now_loading_spr.py `
  .\build\add00_safe_preloading.bin .\build\add00_final.bin `
  --font "$env:LOCALAPPDATA\Microsoft\Windows\Fonts\NanumSquareNeo-cBd.ttf" `
  --logical-payload .\build\now_loading_ko_312x40.c4 `
  --report .\build\now_loading_audit.json

python -X utf8 .\tools\audit_shared_atlas_refs.py `
  .\input\add00dat.bin .\build\add00_final.bin `
  --large-mapping .\data\ui_block518_ko.json `
  --small-mapping .\data\ui_small_and_title_ko.json `
  --report .\build\shared_atlas_audit.json
```

`repack_direct_scr_atlas.py`의 `--vertical-slack`은 라벨마다 비워 두는 주사선
수입니다. 기본값 `0`이 일본판 잉크 높이를 가장 정확히 재현하지만, 아틀라스
`518`은 원본 타일 8,448개 위에 한국어 타일 7,921개를 더해 14비트 인덱스 한계
16,384개에 근접합니다(여유 15개). 번역 문자열을 고쳐 인덱스가 모자라면
`repack_preserve_indices.py`가 그 사실을 알리며 중단하므로, 그때
`--vertical-slack 1` 또는 `2`로 다시 만들면 됩니다. 인덱스 여유는
`ui_preserved_index_audit.json`의 `spare_appendable_tiles`에 기록됩니다.

앞의 두 재패커 결과는 한국어 목표 화면을 만드는 중간 참조 파일입니다.
`add00_visual_reference.bin`을 ISO에 직접 넣으면 동적 타일 번호가 깨질 수
있습니다. 반드시 `repack_preserve_indices.py`와 공유 아틀라스 감사를 거친
`add00_final.bin`만 사용해야 합니다.

재현 명령은 새 `build` 디렉터리에서 실행해야 합니다. 최종 보존형 재패커와
공유 아틀라스 감사 도구는 기존 출력·보고서를 덮어쓰지 않고 중단합니다.
감사 도구는 로딩 이미지 전용 SPR `3508`만 독립 변경으로 기본 허용하며,
매핑에 없는 블록 변경이나 필수 아틀라스·SCR 변경 누락은 실패로 처리합니다.
안전 조건을 하나라도 만족하지 못하면 JSON 보고서를 남긴 뒤 0이 아닌 종료
코드를 반환하므로 자동 빌드에서도 그대로 사용할 수 있습니다.

참조 제작 환경은 Python `3.13.1`, Pillow `11.1.0`, FreeType `2.13.3`입니다.
`requirements.txt`는 픽셀 해시 재현을 위해 Pillow `11.1.0`을 고정합니다.
감사 JSON에는 입력·참고 파일, 매핑 JSON, 글꼴의 SHA-256과 렌더러 버전이
기록됩니다. 동일 입력으로 재현했을 때의 주요 해시는 다음과 같습니다.

| 단계 | SHA-256 |
| --- | --- |
| UI 적용 전 `add00dat.bin` | `D2CF4A8B231A3028207B2BD5D2019FB4E080492B90933A1F10CB1F37F21AA6AB` |
| 일본판 참고 `add00dat.bin` | `7B592F335EDDD016198A8324EF98DEFC942D072D4FB96321AE58BF4E8504E0EF` |
| 영문판 참고 `add00dat.bin` | `E64985BD142EE15AAC4C1967E403F856FB1DE4003F93AC606D497AD33C08AB3B` |
| 대형 아틀라스 매핑 JSON | `2CDE06DA4402B74E389CCDA32EAEBF68E3AF8902902152B654E09F3ADD3EDC7C` |
| 소형·타이틀 매핑 JSON | `2CD0F3224AEE84E0EBC5B0D3788AD86A2FCBE6D0E4D78D8FAFF8BE945233E6AB` |
| 글꼴 `NanumSquareNeo-cBd.ttf` | `4749FA5691157CF56A59D297B45E88894A646846048018CD7A4117FFB2869767` |
| 대형 아틀라스 적용 결과 | `93D871B5F129AE3AEAC1D05788804A7F7CC1C093FB6E035AD772A1A42297D514` |
| 소형·타이틀 시각 참조 결과 | `F2CA4E0FCB1386BBA5495516BE57A072021754BF11B8B33A81443086AF646643` |
| 원본 인덱스 보존 결과 | `842E2E580715A9CA9486474ACB2AB08B261A6CCF302F9A430FD20343E9751FDE` |
| 로딩 이미지까지 적용한 최종 결과 | `744AB20B893F6B4B2891F0F79DF088A14ECDBB93D868C672357726D6C7AAA2E2` |

## 형식과 검증

- 아틀라스 `518`: 하위 14비트 타일 인덱스, 비트 14/15 좌우·상하 반전
- 나머지 아틀라스: 하위 10비트 타일 인덱스, 비트 10/11 좌우·상하 반전
- 로딩 SPR: 312×40 논리 이미지를 `256/32/16/8` 폭과 `32/8` 높이의 C4 텍스처 8개로 분할
- 기존 8×8 타일은 같은 번호에서 바이트 단위로 보존하고 새 한국어 타일만 뒤에 추가
- 번역 대상 `SCR` 452개만 새 타일로 재매핑하고 비문자 `SCR` 32개는 그대로 보존
- 정적 `SCR` 미참조 비공백 타일 1,383개도 동적 참조 후보로 간주해 전부 보존
- 블록 `438`은 10비트 인덱스 한계 때문에 한 글자당 8×8 글리프 하나를 사용
  (라벨 23개의 고유 문자 58자 = 남은 인덱스 64개에 정확히 대응)
- 팔레트·SPR 헤더·CEL을 보존하고, 로딩 SPR `3508`의 TEX 8개 외에는
  아틀라스 밖 블록의 페이로드 변경 금지
- 재구성한 모든 SCR을 다시 렌더링해 목표 이미지와 픽셀 단위 비교
- 확장된 BMP 블록에 맞춰 외부 포인터 테이블만 재계산하고 0x20 정렬 검증

타이틀의 한국어 `슈퍼로봇대전 GC` 로고와 일본판 기반 이벤트 데이터는 이
작업에서 건드리지 않습니다.
