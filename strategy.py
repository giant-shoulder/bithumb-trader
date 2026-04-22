"""
제이슨 노아 '리듬 단타 매매법' - AlphaTrend 기반 3단계 전략

[확인] AT 색상이 green으로 전환 → 추세 전환 캔들 강도 확인
[반응] 전환 이후 눌림목(음봉) 대기 - 절대 추격 매수 금지
[진입] 눌림목 후 반등 양봉에서 진입 / 손절: 눌림목 저점 / 익절: R:R 1:1.5

노이즈 구간 (AT yellow): 진입 금지, 보유 중이면 즉시 청산
"""
import numpy as np
import pandas as pd
from config import (
    MIN_PRICE_KRW,
    AT_PERIOD, AT_MULTIPLIER,
    PULLBACK_MAX_CANDLES,
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
          green  = AT[i] > AT[i-1]  (상승 추세)
          red    = AT[i] < AT[i-1]  (하락 추세)
          yellow = AT[i] == AT[i-1] (횡보/노이즈)
        """
        if period is None:
            period = AT_PERIOD
        if multiplier is None:
            multiplier = AT_MULTIPLIER

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

    # ===== 핵심: 3단계 리듬 진입 (Stateless 역추적) =====

    def check_rhythm_entry(self, coin: str, df: pd.DataFrame,
                            current_price: float = None) -> dict:
        """제이슨 노아 리듬 단타 진입 판단 (Stateless)

        매 폴링마다 완성된 캔들을 역추적하여 패턴 확인:

        [확인] 현재 AT가 green (상승 추세)
        [반응] 최근 PULLBACK_MAX_CANDLES 내 눌림목(음봉) 존재
        [진입] 현재 형성 중인 캔들이 양봉 (반등 확인)

        손절: 눌림목 저점 (클리핑 0.5%~2.5%)
        익절: 진입가 + 리스크 × RR_RATIO (1:1.5)
        """
        result = {
            'signal': False, 'reason': '',
            'stop_loss_price': 0.0, 'take_profit_price': 0.0,
        }

        price = current_price if current_price else df['close'].iloc[-1]

        if price < MIN_PRICE_KRW:
            result['reason'] = f'가격 {price:.0f}원 < {MIN_PRICE_KRW}원'
            return result

        n = len(df)
        if n < AT_PERIOD + PULLBACK_MAX_CANDLES + 3:
            result['reason'] = '데이터 부족'
            return result

        at_df = self.calc_alpha_trend(df)
        colors = at_df['at_color'].tolist()

        # ① 현재 AT가 green이어야 함 (yellow/red = 노이즈/하락 → 진입 금지)
        if colors[-1] != 'green':
            result['reason'] = f'현재 AT {colors[-1]} (진입 금지)'
            return result

        # ② 최근 PULLBACK_MAX_CANDLES 완성 캔들 내 눌림목(음봉) 탐색
        # 가장 최근 음봉의 저점을 손절가 기준으로 사용
        search_start = max(0, n - 1 - PULLBACK_MAX_CANDLES)
        pullback_low = None
        for i in range(n - 2, search_start - 1, -1):  # 최신 완성 캔들 → 과거
            candle = df.iloc[i]
            if candle['close'] < candle['open']:  # 음봉 = 눌림목
                pullback_low = candle['low']
                break  # 가장 최근 눌림목 사용

        if pullback_low is None:
            result['reason'] = f'눌림목(음봉) 없음 (최근 {PULLBACK_MAX_CANDLES}캔들)'
            return result

        # ③ 현재 형성 중인 캔들이 양봉 (반등 확인)
        cur = df.iloc[-1]
        if cur['close'] <= cur['open']:
            result['reason'] = '반등 양봉 대기 중 (현재 음봉)'
            return result

        # ④ 현재가 > AT값
        cur_at = at_df['at_value'].iloc[-1]
        if not np.isnan(cur_at) and price <= cur_at:
            result['reason'] = f'가격({price:.0f}) <= AT({cur_at:.0f})'
            return result

        # ⑤ 손절/익절 계산
        raw_stop_pct = (price - pullback_low) / price * 100
        stop_pct = max(STOP_LOSS_MIN_PCT, min(STOP_LOSS_MAX_PCT, raw_stop_pct))
        stop_loss_price = price * (1 - stop_pct / 100)
        risk = price - stop_loss_price
        take_profit_price = price + risk * RR_RATIO
        target_pct = risk * RR_RATIO / price * 100

        result['signal'] = True
        result['stop_loss_price'] = stop_loss_price
        result['take_profit_price'] = take_profit_price
        result['reason'] = (
            f'리듬 진입 | 눌림목저점={pullback_low:.0f} | '
            f'손절={stop_loss_price:.0f}(-{stop_pct:.1f}%) '
            f'익절={take_profit_price:.0f}(+{target_pct:.1f}%)'
        )
        logger.info(f'[리듬 진입] {coin} | {result["reason"]}')
        return result

    # ===== 노이즈 청산 (AT yellow → 즉시 청산) =====

    def check_at_noise_exit(self, coin: str, df: pd.DataFrame) -> bool:
        """AT yellow 전환 시 즉시 청산 신호"""
        at_df = self.calc_alpha_trend(df)
        cur_color = at_df['at_color'].iloc[-1]
        if cur_color == 'yellow':
            logger.info(f'[AT 노이즈 청산] {coin} | AT yellow → 즉시 청산')
            return True
        return False

    # ===== WebSocket 실시간 손절/익절 =====

    def check_at_stop_take(self, coin: str, current_price: float,
                            stop_loss_price: float, take_profit_price: float) -> dict:
        """절대 가격 기반 손절/익절 (WebSocket 틱 콜백용)"""
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

    # ===== 모멘텀 소멸 =====

    def check_momentum_exit(self, coin: str, volume_rank: int) -> dict:
        result = {'sell': False, 'reason': '', 'is_stop_loss': False}
        if volume_rank > MOMENTUM_KILL_RANK:
            result['sell'] = True
            result['reason'] = f'모멘텀 소멸: 거래대금 {volume_rank}위 (기준 {MOMENTUM_KILL_RANK}위)'
        return result

    # ===== 오더북 매수세 (선택적 필터) =====

    def check_buy_pressure(self, orderbook: dict, trades: list) -> dict:
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

        if bid_ratio >= 1.2 and trade_ratio >= 0.60:
            result['strong'] = True
            result['reason'] = f'매수세 강함 (호가비율={bid_ratio:.2f}, 체결비율={trade_ratio:.0%})'
        else:
            reasons = []
            if bid_ratio < 1.2:
                reasons.append(f'호가비율({bid_ratio:.2f}<1.2)')
            if trade_ratio < 0.60:
                reasons.append(f'체결비율({trade_ratio:.0%}<60%)')
            result['reason'] = ', '.join(reasons)

        return result
