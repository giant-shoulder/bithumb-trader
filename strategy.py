"""
AlphaTrend 기반 리듬 단타 전략 (제이슨 노아 방법론)
3단계: 확인(AT green 전환) → 반응(눌림목 대기) → 진입(반등 양봉)

손익비 R:R 1:1.5
- 손절: 눌림목 캔들 저점 (클리핑 0.5%~2.5%)
- 익절: 진입가 + 리스크 * 1.5
"""
import numpy as np
import pandas as pd
from config import (
    MA_MID1, MA_MID2,
    MIN_PRICE_KRW,
    AT_PERIOD, AT_MULTIPLIER,
    STOP_LOSS_MIN_PCT, STOP_LOSS_MAX_PCT,
    RR_RATIO,
    RSI_PERIOD,
    MOMENTUM_KILL_RANK,
)
from logger import get_logger

logger = get_logger()


class AlphaTrendStrategy:
    """제이슨 노아 리듬 단타 - AlphaTrend 기반"""

    # ===== AlphaTrend 계산 =====

    def _calc_rsi_series(self, df: pd.DataFrame, period: int = None) -> pd.Series:
        """RSI 시리즈 반환 (AT 내부용)"""
        if period is None:
            period = RSI_PERIOD
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(window=period).mean()
        loss = (-delta.clip(upper=0)).rolling(window=period).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def calc_alpha_trend(self, df: pd.DataFrame,
                          period: int = None,
                          multiplier: float = None) -> pd.DataFrame:
        """AlphaTrend 지표 계산

        - RSI >= 50: AT = max(low - ATR*mult, AT_prev)  → 지지선 (상승 추세)
        - RSI <  50: AT = min(high + ATR*mult, AT_prev) → 저항선 (하락 추세)

        Color:
          - green:  AT[i] > AT[i-1]
          - red:    AT[i] < AT[i-1]
          - yellow: AT[i] == AT[i-1] (횡보/노이즈)

        Returns: df에 'at_value', 'at_color' 컬럼 추가한 DataFrame
        """
        if period is None:
            period = AT_PERIOD
        if multiplier is None:
            multiplier = AT_MULTIPLIER

        # ATR (EMA of True Range)
        prev_close = df['close'].shift(1)
        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - prev_close).abs(),
            (df['low'] - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr = tr.ewm(span=period, adjust=False).mean()
        rsi = self._calc_rsi_series(df, period)

        at_arr = np.full(len(df), np.nan)

        for i in range(len(df)):
            if i < period or pd.isna(rsi.iloc[i]) or pd.isna(atr.iloc[i]):
                continue
            prev_at = at_arr[i - 1] if (i > 0 and not np.isnan(at_arr[i - 1])) else df['close'].iloc[i]
            cur_atr = atr.iloc[i] * multiplier
            if rsi.iloc[i] >= 50:
                at_arr[i] = max(df['low'].iloc[i] - cur_atr, prev_at)
            else:
                at_arr[i] = min(df['high'].iloc[i] + cur_atr, prev_at)

        # Color 결정
        at_colors = ['yellow'] * len(df)
        for i in range(1, len(df)):
            if np.isnan(at_arr[i]) or np.isnan(at_arr[i - 1]):
                at_colors[i] = 'yellow'
            elif at_arr[i] > at_arr[i - 1]:
                at_colors[i] = 'green'
            elif at_arr[i] < at_arr[i - 1]:
                at_colors[i] = 'red'
            else:
                at_colors[i] = 'yellow'

        result = df.copy()
        result['at_value'] = at_arr
        result['at_color'] = at_colors
        return result

    # ===== 1단계: 확인 (AT green 전환 감지) =====

    def check_alpha_trend_signal(self, coin: str, df: pd.DataFrame,
                                  current_price: float = None) -> dict:
        """AT green 전환 감지 - 확인 단계

        조건:
        1. 직전 캔들 AT non-green → 현재 캔들 AT green 전환
        2. MA20 > MA60 (중기 상승 추세)
        3. 현재가 > AT 값
        4. 최소 가격 필터
        """
        result = {'signal': False, 'reason': '', 'at_value': 0.0}
        price = current_price if current_price else df['close'].iloc[-1]

        if price < MIN_PRICE_KRW:
            result['reason'] = f'가격 {price:.0f}원 < 최소 {MIN_PRICE_KRW}원'
            return result

        min_len = max(MA_MID2, AT_PERIOD + 2)
        if len(df) < min_len:
            result['reason'] = '데이터 부족'
            return result

        at_df = self.calc_alpha_trend(df)
        cur_color = at_df['at_color'].iloc[-1]
        prev_color = at_df['at_color'].iloc[-2]
        cur_at = at_df['at_value'].iloc[-1]

        if np.isnan(cur_at):
            result['reason'] = 'AT 계산 불가'
            return result

        # AT green 전환 확인
        if not (cur_color == 'green' and prev_color != 'green'):
            result['reason'] = f'AT green 전환 없음 ({prev_color}→{cur_color})'
            return result

        # MA20 > MA60 (중기 상승 추세 필터)
        ma20 = df['close'].rolling(MA_MID1).mean().iloc[-1]
        ma60 = df['close'].rolling(MA_MID2).mean().iloc[-1]
        if ma20 <= ma60:
            result['reason'] = f'MA20({ma20:.0f}) <= MA60({ma60:.0f})'
            return result

        # 현재가 > AT
        if price <= cur_at:
            result['reason'] = f'가격({price:.0f}) <= AT({cur_at:.0f})'
            return result

        result['signal'] = True
        result['at_value'] = cur_at
        result['reason'] = (f'AT green 전환 | MA20={ma20:.0f}>MA60={ma60:.0f} | AT={cur_at:.0f}')
        logger.info(f"[AT 신호] {coin} | {result['reason']}")
        return result

    # ===== 2~3단계: 반응 + 진입 (눌림목 + 반등) =====

    def check_pullback_entry(self, coin: str, df: pd.DataFrame,
                              pending_signal: dict) -> dict:
        """눌림목 반등 진입 판단

        조건:
        1. AT 여전히 green (yellow/red면 신호 취소)
        2. 직전 캔들 음봉 (눌림목)
        3. 현재 캔들 양봉 (반등 확인)
        4. 현재가 > AT 값
        5. 손절 = 직전 음봉 저점 (클리핑 STOP_LOSS_MIN_PCT~STOP_LOSS_MAX_PCT)
        6. 익절 = 진입가 + 리스크 * RR_RATIO
        """
        result = {'entry': False, 'reason': '', 'cancel': False}

        at_df = self.calc_alpha_trend(df)
        cur_color = at_df['at_color'].iloc[-1]
        cur_at = at_df['at_value'].iloc[-1]

        # AT가 green이 아니면 신호 취소
        if cur_color != 'green':
            result['cancel'] = True
            result['reason'] = f'AT {cur_color} - 신호 취소'
            return result

        last = df.iloc[-1]  # 현재 캔들
        prev = df.iloc[-2]  # 직전 캔들 (눌림목 후보)

        # 현재 캔들 양봉 (반등 확인)
        if last['close'] <= last['open']:
            result['reason'] = '현재 음봉 (반등 미확인)'
            return result

        # 직전 캔들 음봉 (눌림목)
        if prev['close'] >= prev['open']:
            result['reason'] = '직전 양봉 (눌림목 없음)'
            return result

        entry_price = last['close']

        # 현재가 > AT
        if entry_price <= cur_at:
            result['reason'] = f'가격({entry_price:.0f}) <= AT({cur_at:.0f})'
            return result

        # 손절가 계산 (눌림목 저점 기반, 클리핑)
        pullback_low = prev['low']
        raw_stop_pct = (entry_price - pullback_low) / entry_price * 100
        stop_pct = max(STOP_LOSS_MIN_PCT, min(STOP_LOSS_MAX_PCT, raw_stop_pct))
        stop_loss_price = entry_price * (1 - stop_pct / 100)

        # 익절가 계산 (R:R = 1:RR_RATIO)
        risk = entry_price - stop_loss_price
        take_profit_price = entry_price + risk * RR_RATIO
        target_pct = risk * RR_RATIO / entry_price * 100

        result.update({
            'entry': True,
            'entry_price': entry_price,
            'stop_loss_price': stop_loss_price,
            'take_profit_price': take_profit_price,
            'stop_pct': stop_pct,
            'target_pct': target_pct,
            'reason': (f'눌림목 반등 진입 | '
                       f'손절={stop_loss_price:.0f}(-{stop_pct:.1f}%) '
                       f'익절={take_profit_price:.0f}(+{target_pct:.1f}%)'),
        })
        logger.info(f"[눌림목 진입] {coin} | {result['reason']}")
        return result

    # ===== 노이즈 청산 =====

    def check_at_noise_exit(self, coin: str, df: pd.DataFrame) -> bool:
        """AT yellow 구간 진입 시 즉시 청산 신호 (AT_NOISE_EXIT=True 시 사용)"""
        at_df = self.calc_alpha_trend(df)
        cur_color = at_df['at_color'].iloc[-1]
        if cur_color == 'yellow':
            logger.info(f"[AT 노이즈 청산] {coin} | AT yellow 전환 → 즉시 청산")
            return True
        return False

    # ===== WebSocket 실시간 손절/익절 =====

    def check_at_stop_take(self, coin: str, current_price: float,
                            stop_loss_price: float, take_profit_price: float) -> dict:
        """절대 가격 기반 손절/익절 판단 (WebSocket 틱 콜백용)

        stop_loss_price / take_profit_price 가 0이면 해당 체크 스킵
        """
        result = {'sell': False, 'reason': '', 'is_stop_loss': False}

        if stop_loss_price > 0 and current_price <= stop_loss_price:
            result['sell'] = True
            result['is_stop_loss'] = True
            result['reason'] = f'손절: {current_price:,.0f}원 <= {stop_loss_price:,.0f}원'
        elif take_profit_price > 0 and current_price >= take_profit_price:
            result['sell'] = True
            result['is_stop_loss'] = False
            result['reason'] = f'익절: {current_price:,.0f}원 >= {take_profit_price:,.0f}원'

        return result

    # ===== 모멘텀 소멸 체크 =====

    def check_momentum_exit(self, coin: str, volume_rank: int) -> dict:
        """거래대금 순위 이탈로 인한 모멘텀 소멸 매도"""
        result = {'sell': False, 'reason': '', 'is_stop_loss': False}
        if volume_rank > MOMENTUM_KILL_RANK:
            result['sell'] = True
            result['reason'] = f'모멘텀 소멸: 거래대금 {volume_rank}위 (기준 {MOMENTUM_KILL_RANK}위)'
        return result

    # ===== 오더북 매수세 (진입 필터) =====

    def check_buy_pressure(self, orderbook: dict, trades: list) -> dict:
        """호가 및 체결 기반 매수세 분석"""
        result = {'strong': False, 'bid_ratio': 0.0, 'trade_ratio': 0.0, 'reason': ''}

        if orderbook:
            units = orderbook.get('orderbook_units', [])
            total_bid = sum(float(u.get('bid_size', 0)) * float(u.get('bid_price', 0)) for u in units)
            total_ask = sum(float(u.get('ask_size', 0)) * float(u.get('ask_price', 0)) for u in units)
            bid_ratio = total_bid / total_ask if total_ask > 0 else 0
            result['bid_ratio'] = bid_ratio
        else:
            bid_ratio = 0

        if trades:
            buy_count = sum(1 for t in trades if t.get('ask_bid') == 'BID')
            trade_ratio = buy_count / len(trades)
            result['trade_ratio'] = trade_ratio
        else:
            trade_ratio = 0

        bid_ok = bid_ratio >= 1.2
        trade_ok = trade_ratio >= 0.60

        if bid_ok and trade_ok:
            result['strong'] = True
            result['reason'] = f'매수세 강함 (호가비율={bid_ratio:.2f}, 체결비율={trade_ratio:.0%})'
        else:
            reasons = []
            if not bid_ok:
                reasons.append(f'호가비율 약함({bid_ratio:.2f}<1.2)')
            if not trade_ok:
                reasons.append(f'체결비율 약함({trade_ratio:.0%}<60%)')
            result['reason'] = ', '.join(reasons)

        return result
