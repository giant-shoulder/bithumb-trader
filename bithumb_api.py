"""
빗섬 API 래퍼
pybithumb 라이브러리 기반
"""
import time
import pybithumb
import pandas as pd
from config import BITHUMB_ACCESS_KEY, BITHUMB_SECRET_KEY
from logger import get_logger

logger = get_logger()


class BithumbAPI:
    def __init__(self):
        self.bithumb = pybithumb.Bithumb(BITHUMB_ACCESS_KEY, BITHUMB_SECRET_KEY)

    # ===== 시세 조회 =====

    def get_current_price(self, coin: str) -> float | None:
        """현재가 조회"""
        try:
            price = pybithumb.get_current_price(coin)
            return float(price)
        except Exception as e:
            logger.error(f"현재가 조회 실패 [{coin}]: {e}")
            return None

    def get_ohlcv(self, coin: str, interval: str = "1h", count: int = 200) -> pd.DataFrame | None:
        """캔들 데이터 조회
        interval: '1m', '3m', '5m', '10m', '30m', '1h', '6h', '12h', '24h'
        """
        try:
            df = pybithumb.get_candlestick(coin, chart_intervals=interval)
            if df is None or df.empty:
                return None
            df = df.tail(count).copy()
            df.columns = ['open', 'close', 'high', 'low', 'volume']
            df = df.astype(float)
            return df
        except Exception as e:
            logger.error(f"캔들 조회 실패 [{coin}]: {e}")
            return None

    def get_ticker_all(self) -> dict | None:
        """전체 코인 시세 조회 (거래대금 계산용)"""
        try:
            tickers = pybithumb.get_tickers()
            result = {}
            for coin in tickers:
                try:
                    data = pybithumb.get_current_price("ALL", payment_currency="KRW")
                    if data:
                        result = data
                        break
                except:
                    pass
            return result
        except Exception as e:
            logger.error(f"전체 시세 조회 실패: {e}")
            return None

    def get_volume_ranking(self, watchlist: list, top_n: int = 5) -> list:
        """거래대금 상위 코인 반환"""
        try:
            volumes = []
            for coin in watchlist:
                try:
                    df = pybithumb.get_candlestick(coin, chart_intervals="24h")
                    if df is not None and not df.empty:
                        last = df.iloc[-1]
                        # 거래대금 = 종가 * 거래량
                        volume_krw = float(last['close']) * float(last['volume'])
                        change_pct = (float(last['close']) - float(last['open'])) / float(last['open']) * 100
                        volumes.append({
                            'coin': coin,
                            'volume_krw': volume_krw,
                            'change_pct': change_pct,
                            'price': float(last['close'])
                        })
                    time.sleep(0.1)  # API 호출 제한
                except Exception as e:
                    logger.warning(f"거래대금 조회 실패 [{coin}]: {e}")
                    continue

            volumes.sort(key=lambda x: x['volume_krw'], reverse=True)
            return volumes[:top_n]
        except Exception as e:
            logger.error(f"거래대금 순위 조회 실패: {e}")
            return []

    # ===== 잔고 조회 =====

    def get_balance(self, coin: str = "KRW") -> float:
        """잔고 조회"""
        try:
            balance = self.bithumb.get_balance(coin)
            if balance and len(balance) >= 2:
                return float(balance[0])  # 보유수량
            return 0.0
        except Exception as e:
            logger.error(f"잔고 조회 실패 [{coin}]: {e}")
            return 0.0

    def get_krw_balance(self) -> float:
        """원화 잔고"""
        try:
            balance = self.bithumb.get_balance("BTC")  # KRW 잔고는 BTC 조회시 함께 옴
            if balance and len(balance) >= 4:
                return float(balance[2])  # KRW 잔고
            return 0.0
        except Exception as e:
            logger.error(f"원화 잔고 조회 실패: {e}")
            return 0.0

    # ===== 주문 =====

    def buy_market(self, coin: str, krw_amount: float) -> dict | None:
        """시장가 매수"""
        try:
            result = self.bithumb.buy_market_order(coin, krw_amount)
            logger.info(f"시장가 매수 [{coin}] {krw_amount:,.0f}원 → {result}")
            return result
        except Exception as e:
            logger.error(f"시장가 매수 실패 [{coin}]: {e}")
            return None

    def sell_market(self, coin: str, quantity: float) -> dict | None:
        """시장가 매도"""
        try:
            result = self.bithumb.sell_market_order(coin, quantity)
            logger.info(f"시장가 매도 [{coin}] {quantity} → {result}")
            return result
        except Exception as e:
            logger.error(f"시장가 매도 실패 [{coin}]: {e}")
            return None

    def buy_limit(self, coin: str, price: float, quantity: float) -> dict | None:
        """지정가 매수"""
        try:
            result = self.bithumb.buy_limit_order(coin, price, quantity)
            logger.info(f"지정가 매수 [{coin}] {price:,.0f}원 x {quantity} → {result}")
            return result
        except Exception as e:
            logger.error(f"지정가 매수 실패 [{coin}]: {e}")
            return None

    def sell_limit(self, coin: str, price: float, quantity: float) -> dict | None:
        """지정가 매도"""
        try:
            result = self.bithumb.sell_limit_order(coin, price, quantity)
            logger.info(f"지정가 매도 [{coin}] {price:,.0f}원 x {quantity} → {result}")
            return result
        except Exception as e:
            logger.error(f"지정가 매도 실패 [{coin}]: {e}")
            return None
