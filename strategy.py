"""
홍인기 단타 전략 - 코인 버전
핵심: 거래대금 1등 + 정배열 + 장대양봉 돌파 매수
"""
import pandas as pd
import numpy as np
from config import (
    MA_SHORT, MA_MID1, MA_MID2, MA_LONG,
    RSI_BUY_MIN, RSI_BUY_MAX,
    BULLISH_CANDLE_MIN, PREV_HIGH_PERIOD,
    MOMENTUM_TOP_N,
    ATR_PERIOD,
    HARD_STOP_ATR_MULT, HARD_STOP_MIN_PCT, HARD_STOP_MAX_PCT,
    BREAKEVEN_TRIGGER_ATR, TRAILING_PHASE2_ATR,
    PROFIT_TRIGGER_ATR, TRAILING_PHASE3_ATR,
    RSI_PERIOD, RSI_OVERBOUGHT,
    BB_PERIOD, BB_STD,
)
from logger import get_logger

logger = get_logger()


class HongStrategy:
    """홍인기 단타 전략"""

    # ===== 이동평균 =====

    def calc_ma(self, df: pd.DataFrame, period: int) -> pd.Series:
        """이동평균 계산"""
        return df['close'].rolling(window=period).mean()

    def is_bullish_alignment(self, df: pd.DataFrame) -> bool:
        """정배열 확인: MA5 > MA20 > MA60 > MA120
        코인 특성상 MA120이 없을 수 있으므로 MA5 > MA20 > MA60 기준
        """
        if len(df) < MA_LONG:
            # 데이터 부족 시 단기 정배열만 확인
            if len(df) < MA_MID2:
                return False
            ma5 = self.calc_ma(df, MA_SHORT).iloc[-1]
            ma20 = self.calc_ma(df, MA_MID1).iloc[-1]
            ma60 = self.calc_ma(df, MA_MID2).iloc[-1]
            result = ma5 > ma20 > ma60
        else:
            ma5 = self.calc_ma(df, MA_SHORT).iloc[-1]
            ma20 = self.calc_ma(df, MA_MID1).iloc[-1]
            ma60 = self.calc_ma(df, MA_MID2).iloc[-1]
            ma120 = self.calc_ma(df, MA_LONG).iloc[-1]
            result = ma5 > ma20 > ma60 > ma120

        logger.debug(f"정배열: {result} | MA5={ma5:.0f} MA20={ma20:.0f} MA60={ma60:.0f}")
        return result

    # ===== 장대양봉 =====

    def is_bullish_candle(self, df: pd.DataFrame) -> bool:
        """장대양봉 확인: 시가 대비 종가 상승폭이 기준 이상"""
        last = df.iloc[-1]
        open_price = last['open']
        close_price = last['close']
        if open_price <= 0:
            return False
        candle_rise = (close_price - open_price) / open_price * 100
        result = candle_rise >= BULLISH_CANDLE_MIN
        logger.debug(f"장대양봉: {result} | 캔들 상승률={candle_rise:.2f}%")
        return result

    # ===== 전고점 돌파 =====

    def is_breaking_high(self, df: pd.DataFrame) -> bool:
        """6개월(120캔들) 내 전고점 돌파 여부"""
        if len(df) < 2:
            return False
        period = min(PREV_HIGH_PERIOD, len(df) - 1)
        prev_high = df['high'].iloc[-period:-1].max()
        current_close = df['close'].iloc[-1]
        result = current_close >= prev_high
        logger.debug(f"전고점 돌파: {result} | 현재={current_close:.0f} 전고점={prev_high:.0f}")
        return result

    # ===== 거래대금 급증 =====

    def is_volume_surge(self, df: pd.DataFrame, multiplier: float = 2.0) -> bool:
        """거래대금 급증 확인: 평균 대비 N배 이상"""
        if len(df) < 20:
            return False
        avg_volume = df['volume'].iloc[-20:-1].mean()
        current_volume = df['volume'].iloc[-1]
        result = current_volume >= avg_volume * multiplier
        logger.debug(f"거래대금 급증: {result} | 현재={current_volume:.0f} 평균={avg_volume:.0f}")
        return result

    # ===== 지지/저항 =====

    def get_resistance_levels(self, df: pd.DataFrame, current_price: float) -> list:
        """저항선 계산: 전고점, 라운드넘버"""
        levels = []

        # 전고점들
        highs = df['high'].iloc[-PREV_HIGH_PERIOD:].values
        for h in sorted(set([round(x, -int(np.log10(x))-1+3) for x in highs if x > current_price]))[:3]:
            levels.append(h)

        # 라운드넘버 (10의 배수)
        magnitude = 10 ** int(np.log10(current_price))
        for i in range(1, 5):
            round_num = (int(current_price / magnitude) + i) * magnitude
            levels.append(round_num)

        levels = sorted(set([l for l in levels if l > current_price]))
        return levels[:3]

    def get_support_levels(self, df: pd.DataFrame, current_price: float) -> list:
        """지지선 계산: 이동평균선"""
        supports = []
        for period in [MA_SHORT, MA_MID1, MA_MID2]:
            if len(df) >= period:
                ma = self.calc_ma(df, period).iloc[-1]
                if ma < current_price:
                    supports.append(ma)
        return sorted(supports, reverse=True)

    # ===== 기술 지표 =====

    def calc_rsi(self, df: pd.DataFrame) -> float:
        """RSI 계산"""
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(window=RSI_PERIOD).mean()
        loss = (-delta.clip(upper=0)).rolling(window=RSI_PERIOD).mean()
        rs = gain / loss.replace(0, float('nan'))
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1], rsi.iloc[-2]

    def calc_bollinger_bands(self, df: pd.DataFrame) -> tuple:
        """볼린저 밴드 계산 (upper, mid, lower)"""
        ma = df['close'].rolling(window=BB_PERIOD).mean()
        std = df['close'].rolling(window=BB_PERIOD).std()
        return (ma + BB_STD * std).iloc[-1], ma.iloc[-1], (ma - BB_STD * std).iloc[-1]

    def calc_atr(self, df: pd.DataFrame) -> float:
        """ATR (Average True Range) 계산 - 코인별 변동성 지표"""
        high = df['high']
        low = df['low']
        close = df['close']
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(window=ATR_PERIOD).mean().iloc[-1]

    def calc_atr_pct(self, df: pd.DataFrame) -> float:
        """ATR을 현재가 대비 퍼센트로 변환"""
        atr = self.calc_atr(df)
        current_price = df['close'].iloc[-1]
        return (atr / current_price) * 100 if current_price > 0 else 1.0

    def calc_macd(self, df: pd.DataFrame) -> tuple:
        """MACD 계산 (macd_cur, signal_cur, macd_prev, signal_prev)"""
        exp12 = df['close'].ewm(span=12, adjust=False).mean()
        exp26 = df['close'].ewm(span=26, adjust=False).mean()
        macd = exp12 - exp26
        signal = macd.ewm(span=9, adjust=False).mean()
        return macd.iloc[-1], signal.iloc[-1], macd.iloc[-2], signal.iloc[-2]

    # ===== 손절/익절 판단 =====

    def should_stop_loss(self, buy_price: float, current_price: float) -> bool:
        """손절 조건: 매입가 대비 -1%"""
        change_pct = (current_price - buy_price) / buy_price * 100
        return change_pct <= STOP_LOSS_PCT

    def should_trailing_stop(self, current_price: float, highest_price: float, buy_price: float) -> bool:
        """트레일링 스탑: 고점 대비 TRAILING_STOP_PCT% 하락 (TRAILING_STOP_TRIGGER% 이상 수익 중일 때 활성화)"""
        gain_pct = (highest_price - buy_price) / buy_price * 100
        if gain_pct < TRAILING_STOP_TRIGGER:
            return False
        drop_from_high = (highest_price - current_price) / highest_price * 100
        return drop_from_high >= TRAILING_STOP_PCT

    def should_sell_rsi(self, df: pd.DataFrame) -> bool:
        """RSI 과매수 반전: RSI가 과매수 구간에서 하락 전환"""
        rsi_cur, rsi_prev = self.calc_rsi(df)
        return rsi_prev >= RSI_OVERBOUGHT and rsi_cur < rsi_prev

    def should_sell_bb(self, df: pd.DataFrame, current_price: float) -> bool:
        """볼린저 밴드 상단 터치"""
        upper, _, _ = self.calc_bollinger_bands(df)
        return current_price >= upper

    def should_sell_macd(self, df: pd.DataFrame) -> bool:
        """MACD 데드크로스: MACD가 시그널 아래로 교차"""
        macd_cur, signal_cur, macd_prev, signal_prev = self.calc_macd(df)
        return macd_prev >= signal_prev and macd_cur < signal_cur

    # ===== 종합 매수 신호 =====

    def check_buy_signal(self, coin: str, df: pd.DataFrame, momentum_score: float) -> dict:
        """매수 신호 종합 판단 (동적 스캔 기반)

        필수 조건:
          1. MA5 > MA20 (단기 상승 추세)
          2. RSI 40~65 (모멘텀 있되 과열 아님)
          3. 가격 > BB 중간선 (상승 편향)

        가산 조건 (보너스):
          4. 거래대금 급증
          5. 전고점 돌파
          6. 정배열 (MA5 > MA20 > MA60)
        """
        result = {
            'coin': coin,
            'buy': False,
            'rsi': 0.0,
            'reasons': [],
            'fail_reasons': []
        }

        if len(df) < BB_PERIOD:
            result['fail_reasons'].append("데이터 부족")
            return result

        ma5 = self.calc_ma(df, MA_SHORT).iloc[-1]
        ma20 = self.calc_ma(df, MA_MID1).iloc[-1]
        rsi_cur, _ = self.calc_rsi(df)
        _, bb_mid, _ = self.calc_bollinger_bands(df)
        current_price = df['close'].iloc[-1]

        result['rsi'] = rsi_cur

        # 1. MA5 > MA20 (필수)
        if ma5 <= ma20:
            result['fail_reasons'].append(f"MA5({ma5:.0f}) ≤ MA20({ma20:.0f})")
            return result
        result['reasons'].append("MA5 > MA20 ✓")

        # 2. RSI 매수 구간 (필수)
        if not (RSI_BUY_MIN <= rsi_cur <= RSI_BUY_MAX):
            result['fail_reasons'].append(f"RSI {rsi_cur:.1f} (기준: {RSI_BUY_MIN}~{RSI_BUY_MAX})")
            return result
        result['reasons'].append(f"RSI {rsi_cur:.1f} ✓")

        # 3. 가격 > BB 중간선 (필수)
        if current_price <= bb_mid:
            result['fail_reasons'].append(f"가격({current_price:.0f}) ≤ BB중간({bb_mid:.0f})")
            return result
        result['reasons'].append("BB 중간선 위 ✓")

        # 4. 거래대금 급증 (보너스)
        if self.is_volume_surge(df):
            result['reasons'].append("거래대금 급증 ✓")

        # 5. 전고점 돌파 (보너스)
        if self.is_breaking_high(df):
            result['reasons'].append("전고점 돌파 ✓")

        # 6. 정배열 (보너스)
        if self.is_bullish_alignment(df):
            result['reasons'].append("정배열 ✓")

        result['buy'] = True
        return result

    # ===== 매도 신호 =====

    def check_sell_signal(self, coin: str, df: pd.DataFrame,
                          buy_price: float, current_price: float,
                          volume_rank: int, highest_price: float = None) -> dict:
        """ATR 기반 3단계 매도 신호

        Phase 1 (매수 직후): 하드 손절만 (ATR × 1.5, 최소 0.8% ~ 최대 3%)
        Phase 2 (수익 >= 1×ATR): 본전 컷 + 트레일링 (ATR × 0.7)
        Phase 3 (수익 >= 2×ATR): 타이트한 트레일링 (ATR × 0.5) + RSI/BB 매도
        """
        result = {
            'coin': coin,
            'sell': False,
            'reason': '',
            'emergency': False
        }

        if highest_price is None:
            highest_price = current_price

        pct = (current_price - buy_price) / buy_price * 100
        atr_pct = self.calc_atr_pct(df)

        # 하드 손절 한계 계산 (ATR 기반, 클램프)
        hard_stop = min(max(atr_pct * HARD_STOP_ATR_MULT, HARD_STOP_MIN_PCT), HARD_STOP_MAX_PCT)

        # Phase 판단 (ATR 배수 기준)
        gain_in_atr = pct / atr_pct if atr_pct > 0 else 0

        # === 하드 손절 (모든 Phase 공통) ===
        if pct <= -hard_stop:
            result['sell'] = True
            result['emergency'] = True
            result['reason'] = f"하드 손절: {pct:.2f}% (ATR 기반 한계: -{hard_stop:.2f}%)"
            return result

        # === Phase 3: 수익 >= 2×ATR ===
        if gain_in_atr >= PROFIT_TRIGGER_ATR:
            trailing_pct = atr_pct * TRAILING_PHASE3_ATR
            drop_from_high = (highest_price - current_price) / highest_price * 100
            if drop_from_high >= trailing_pct:
                result['sell'] = True
                result['reason'] = f"Phase3 트레일링: 고점 대비 -{drop_from_high:.2f}% (수익 {pct:+.2f}%)"
                return result
            if self.should_sell_rsi(df):
                result['sell'] = True
                result['reason'] = f"RSI 과매수 반전 (수익 {pct:+.2f}%, Phase3)"
                return result
            if self.should_sell_bb(df, current_price):
                result['sell'] = True
                result['reason'] = f"BB 상단 도달 (수익 {pct:+.2f}%, Phase3)"
                return result

        # === Phase 2: 수익 >= 1×ATR ===
        elif gain_in_atr >= BREAKEVEN_TRIGGER_ATR:
            if pct <= 0:
                result['sell'] = True
                result['reason'] = f"본전 컷: {pct:.2f}% (Phase2 진입 후 반락)"
                return result
            trailing_pct = atr_pct * TRAILING_PHASE2_ATR
            drop_from_high = (highest_price - current_price) / highest_price * 100
            if drop_from_high >= trailing_pct:
                result['sell'] = True
                result['reason'] = f"Phase2 트레일링: 고점 대비 -{drop_from_high:.2f}% (수익 {pct:+.2f}%)"
                return result

        # === 모멘텀 소멸 (모든 Phase 공통) ===
        if volume_rank > MOMENTUM_TOP_N * 2:
            result['sell'] = True
            result['reason'] = f"모멘텀 소멸: 스캔 {volume_rank}위 밖"
            return result

        return result
