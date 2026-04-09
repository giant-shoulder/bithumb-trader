"""
빗섬 자동매매 설정 파일
실제 API 키는 환경변수로 관리하세요.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ===== API 설정 =====
BITHUMB_ACCESS_KEY = os.environ.get("BITHUMB_ACCESS_KEY", "여기에_액세스키_입력")
BITHUMB_SECRET_KEY = os.environ.get("BITHUMB_SECRET_KEY", "여기에_시크릿키_입력")

# ===== 동적 종목 스캔 =====
MIN_VOLUME_24H_KRW = 2_000_000_000  # 최소 24h 거래대금 (20억 KRW)
MOMENTUM_TOP_N = 50                  # 심층 분석 상위 N개 (20→50, 모멘텀 소멸 오탐 방지)
COIN_BLACKLIST = {'USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'FDUSD',  # 스테이블 코인 제외
                  'GOAT', 'XVS', 'XTER',                            # 반복 손절 (2026-03-30)
                  'WIKEN', 'AZIT', 'CAMP', 'ZRC',                   # 초저가 스프레드 손실 (2026-03-31)
                  'DAO', 'RESOLV',                                   # 반복 하드 손절 (2026-04-01)
                  'KAIA',                                             # 반복 하드 손절 (2026-04-08)
                  'VIRTUAL', 'SWAP',                                  # 하드 손절 (2026-04-09)
                  'BTC', 'XRP'}                                      # 제외 종목 (사용자 설정)

# ===== 전략 파라미터 =====
# 이동평균
MA_SHORT = 5      # 단기
MA_MID1 = 20      # 중기1
MA_MID2 = 60      # 중기2
MA_LONG = 120     # 장기

# 매수 조건
RSI_BUY_MIN = 40             # 매수 RSI 하한 (과매도 제외)
RSI_BUY_MAX = 65             # 매수 RSI 상한 (68→60→65, 매매기회 확대)
BULLISH_CANDLE_MIN = 3.0     # 장대양봉 최소 크기 (시가 대비 %)
PREV_HIGH_PERIOD = 120       # 전고점 기간 (캔들 수)
MIN_PRICE_KRW = 50           # 최소 코인 가격 (원) - 초저가 코인 스프레드 손실 방지 (2026-03-31)

# 매수 실행
MAX_POSITION_KRW = 1050000   # 코인당 최대 투자금액 (원)
BUY_SPLIT = 5                # 불타기 분할 횟수
BUY_UNIT_KRW = 210000        # 1회 매수 금액 (15만→21만)
MAX_CONCURRENT_POSITIONS = 3  # 최대 동시 포지션 수

# ===== 손절/익절 (고정값, 단순) =====
HARD_STOP_PCT = 1.2           # 하드 손절 (%) - 슬리피지 감안 1.5→1.2%
HARD_STOP_MIN_HOLD_SECONDS = 5   # 하드 손절 최소 보유시간 (초) - 45→15→5초
TRAILING_ACTIVATE_PCT = 0.5   # 트레일링 스탑 활성화 수익 기준 (1.0→0.7→0.5%)

# 티어드 트레일링 스탑: 수익이 클수록 더 넓게 추격
# (수익 하한, 트레일링 폭) - 위에서부터 매칭
TRAILING_TIERS = [
    (5.0, 2.5),   # +5% 이상 수익 → 고점 대비 -2.5% 허용 (대형 트렌드 탑승)
    (2.0, 1.5),   # +2% 이상 수익 → 고점 대비 -1.5% 허용 (중형 트렌드)
    (1.0, 1.0),   # +1% 이상 수익 → 고점 대비 -1.0% 허용 (신설 - 더 달리기)
    (0.5, 0.5),   # +0.5% 이상 수익 → 고점 대비 -0.5% 허용
]
HARD_TAKE_PROFIT_PCT = 10.0   # 안전망 익절 (15→10, 익절 기회 앞당기기)
MOMENTUM_KILL_RANK = 50       # 모멘텀 소멸 기준 순위 (40→50, TOP_N=50에 맞게)
MIN_PROFIT_FOR_SELL = 0.4     # 지표 기반 매도 최소 수익률 (%) - RSI/MACD/BB 매도 조건

# 최소 보유 시간 (하드손절 제외한 일반 매도에만 적용)
MIN_HOLD_SECONDS = 180        # 매수 후 최소 보유 시간 (초)

# 매도 후 재매수 금지 시간 (손절/익절에 따라 다르게 적용)
COOLDOWN_AFTER_STOP_LOSS = 3600   # 손절 후 쿨다운 (초) - 1시간
COOLDOWN_AFTER_TAKE_PROFIT = 14400  # 익절/모멘텀소멸 후 쿨다운 (초) - 4시간 (1시간→4시간, 당일 재진입 손절 방지)

# RSI
RSI_PERIOD = 14
RSI_OVERBOUGHT = 72

# 볼린저 밴드
BB_PERIOD = 20
BB_STD = 2.0

# ===== 거래 시간 제한 =====
TRADING_BLOCK_START = 0   # 매수 차단 시작 (KST) - 자정부터 차단 (00시 수익률 나빠서 확장)
TRADING_BLOCK_END = 8     # 매수 차단 종료 (KST)

# ===== 캔들 간격 =====
BUY_CANDLE_INTERVAL = "5m"   # 매수 신호용 캔들 간격
BUY_CANDLE_COUNT = 200        # 매수 신호용 캔들 개수

# ===== 루프 설정 =====
POLLING_INTERVAL_IDLE = 30    # 포지션 없을 때 실행 주기 (초)
POLLING_INTERVAL_ACTIVE = 5   # 포지션 있을 때 실행 주기 (초) (10→5, 손절 슬리피지 감소)
LOG_FILE = "trades.log"       # 로그 파일명

# ===== 리스크 관리 =====
DAILY_LOSS_LIMIT_PCT = 5.0    # 일일 최대 손실 한도 (원금 대비 %)
DAILY_COIN_STOP_LIMIT = 1     # 코인별 일일 손절 한도 (2→1, 1회 손절 시 당일 차단)

# 지정가 매수 설정
BUY_LIMIT_OFFSET_PCT = 0.1   # 현재가 대비 지정가 매수 호가 여유폭 (%)

# 소액 포지션 방지
MIN_BUY_KRW = 100_000        # 최소 실제 매수금액 (원) - 잔고 부족 시 소액 포지션 차단
