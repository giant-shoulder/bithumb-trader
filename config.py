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
MOMENTUM_TOP_N = 50                  # 심층 분석 상위 N개
COIN_BLACKLIST = {'USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'FDUSD',  # 스테이블 코인 제외
                  'GOAT', 'XVS', 'XTER',                            # 반복 손절 (2026-03-30)
                  'WIKEN', 'AZIT', 'CAMP', 'ZRC',                   # 초저가 스프레드 손실 (2026-03-31)
                  'DAO', 'RESOLV',                                   # 반복 하드 손절 (2026-04-01)
                  'KAIA',                                             # 반복 하드 손절 (2026-04-08)
                  'VIRTUAL', 'SWAP',                                  # 하드 손절 (2026-04-09)
                  'PHA',                                              # 초저가(64원) 하드 손절 (2026-04-11)
                  'BTC', 'XRP'}                                      # 제외 종목 (사용자 설정)

# ===== 이동평균 =====
MA_SHORT = 5      # 단기
MA_MID1 = 20      # 중기1
MA_MID2 = 60      # 중기2
MA_LONG = 120     # 장기

# ===== AlphaTrend 파라미터 (제이슨 노아 리듬 단타) =====
AT_PERIOD = 13            # AlphaTrend RSI/ATR 기간
AT_MULTIPLIER = 0.3       # ATR 승수 (지지/저항선 폭)
PULLBACK_MAX_CANDLES = 3  # 눌림목 대기 최대 캔들 수 (5분봉 기준 15분)
STOP_LOSS_MIN_PCT = 0.5   # 손절폭 최솟값 (%)
STOP_LOSS_MAX_PCT = 2.5   # 손절폭 최댓값 (%)
RR_RATIO = 1.5            # 손익비 (Risk:Reward 1:1.5)
AT_NOISE_EXIT = True      # AT yellow 구간 즉시 청산

# ===== RSI =====
RSI_PERIOD = 14

# ===== 모멘텀 소멸 기준 =====
MOMENTUM_KILL_RANK = 50   # 이 순위 밖이면 모멘텀 소멸로 판단

# ===== 매수 실행 =====
MAX_POSITION_KRW = 1000000   # 코인당 최대 투자금액 (원)
BUY_UNIT_KRW = 200000        # 1회 매수 금액
MAX_CONCURRENT_POSITIONS = 3  # 최대 동시 포지션 수

# ===== 최소 가격 =====
MIN_PRICE_KRW = 200          # 최소 코인 가격 (원) - 200원 미만 슬리피지 손절 불가피

# ===== 매도 후 재매수 금지 시간 =====
COOLDOWN_AFTER_STOP_LOSS = 3600    # 손절 후 쿨다운 (초) - 1시간
COOLDOWN_AFTER_TAKE_PROFIT = 14400 # 익절 후 쿨다운 (초) - 4시간

# ===== 거래 시간 제한 =====
TRADING_BLOCK_START = None  # 매수 차단 없음 (시간 제한 해제)
TRADING_BLOCK_END = None    # 매수 차단 없음 (시간 제한 해제)

# ===== 캔들 간격 =====
BUY_CANDLE_INTERVAL = "5m"   # 매수 신호용 캔들 간격
BUY_CANDLE_COUNT = 200        # 매수 신호용 캔들 개수

# ===== 루프 설정 =====
POLLING_INTERVAL_IDLE = 30    # 포지션 없을 때 실행 주기 (초)
POLLING_INTERVAL_ACTIVE = 5   # 포지션 있을 때 실행 주기 (초)
LOG_FILE = "trades.log"       # 로그 파일명

# ===== 리스크 관리 =====
DAILY_LOSS_LIMIT_PCT = 5.0    # 일일 최대 손실 한도 (원금 대비 %)
DAILY_COIN_STOP_LIMIT = 1     # 코인별 일일 손절 한도 (1회 손절 시 당일 차단)

# 지정가 매수 설정
BUY_LIMIT_OFFSET_PCT = 0.1   # 현재가 대비 지정가 매수 호가 여유폭 (%)

# 소액 포지션 방지
MIN_BUY_KRW = 100_000        # 최소 실제 매수금액 (원) - 잔고 부족 시 소액 포지션 차단
MIN_POSITION_KRW = 5_000     # 포지션 인식 최소금액 (원) - 이하는 더스트로 간주

# 우선 매수 종목 (잔고 생기면 다른 종목보다 먼저 검토)
PRIORITY_COINS = {'ETH'}
