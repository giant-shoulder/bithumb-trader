"""
빗섬 API 래퍼
pybithumb 라이브러리 기반
"""
import time
import uuid
import hashlib
import urllib.parse
import jwt
import requests
import pybithumb
import pandas as pd
from config import BITHUMB_ACCESS_KEY, BITHUMB_SECRET_KEY
from logger import get_logger

REST_URL = "https://api.bithumb.com"

logger = get_logger()


class BithumbAPI:
    def __init__(self):
        self.bithumb = pybithumb.Bithumb(BITHUMB_ACCESS_KEY, BITHUMB_SECRET_KEY)

    def _auth_header(self, params: dict = None) -> dict:
        """JWT 인증 헤더 생성"""
        payload = {
            'access_key': BITHUMB_ACCESS_KEY,
            'nonce': str(uuid.uuid4()),
            'timestamp': round(time.time() * 1000),
        }
        if params:
            query_string = urllib.parse.urlencode(params).encode()
            payload['query_hash'] = hashlib.sha512(query_string).hexdigest()
            payload['query_hash_alg'] = 'SHA512'
        token = jwt.encode(payload, BITHUMB_SECRET_KEY, algorithm='HS256')
        return {'Authorization': f'Bearer {token}'}

    def _private_get(self, path: str, params: dict = None) -> dict | list | None:
        """Private GET 요청"""
        try:
            headers = self._auth_header(params)
            resp = requests.get(f"{REST_URL}{path}", headers=headers, params=params, timeout=10)
            return resp.json()
        except Exception as e:
            logger.error(f"Private GET 실패 [{path}]: {e}")
            return None

    def _private_post(self, path: str, body: dict) -> dict | None:
        """Private POST 요청"""
        try:
            payload = {
                'access_key': BITHUMB_ACCESS_KEY,
                'nonce': str(uuid.uuid4()),
                'timestamp': round(time.time() * 1000),
            }
            query_string = urllib.parse.urlencode(body).encode()
            payload['query_hash'] = hashlib.sha512(query_string).hexdigest()
            payload['query_hash_alg'] = 'SHA512'
            token = jwt.encode(payload, BITHUMB_SECRET_KEY, algorithm='HS256')
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            }
            resp = requests.post(f"{REST_URL}{path}", headers=headers, json=body, timeout=10)
            return resp.json()
        except Exception as e:
            logger.error(f"Private POST 실패 [{path}]: {e}")
            return None

    def _private_delete(self, path: str, params: dict) -> dict | None:
        """Private DELETE 요청"""
        try:
            headers = self._auth_header(params)
            resp = requests.delete(f"{REST_URL}{path}", headers=headers, params=params, timeout=10)
            return resp.json()
        except Exception as e:
            logger.error(f"Private DELETE 실패 [{path}]: {e}")
            return None

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

    def get_all_krw_markets(self) -> list[str]:
        """전체 KRW 마켓 코드 조회"""
        try:
            resp = requests.get(f"{REST_URL}/v1/market/all", timeout=10)
            data = resp.json()
            return [item['market'] for item in data if item['market'].startswith('KRW-')]
        except Exception as e:
            logger.error(f"마켓 목록 조회 실패: {e}")
            return []

    def get_tickers_bulk(self, markets: list[str]) -> list[dict]:
        """여러 종목 현재가 일괄 조회 (100개씩 배치)"""
        result = []
        for i in range(0, len(markets), 100):
            batch = markets[i:i + 100]
            try:
                resp = requests.get(
                    f"{REST_URL}/v1/ticker",
                    params={'markets': ','.join(batch)},
                    timeout=10
                )
                data = resp.json()
                if isinstance(data, list):
                    result.extend(data)
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"티커 일괄 조회 실패: {e}")
        return result

    def scan_momentum_coins(self, min_volume_24h: float, top_n: int) -> list[dict]:
        """전체 KRW 종목 모멘텀 스캔 → 상위 N개 반환"""
        markets = self.get_all_krw_markets()
        if not markets:
            return []

        tickers = self.get_tickers_bulk(markets)
        candidates = []

        for t in tickers:
            try:
                volume_24h = float(t.get('acc_trade_price_24h') or 0)
                change_rate = float(t.get('signed_change_rate') or 0) * 100
                price = float(t.get('trade_price') or 0)

                if volume_24h < min_volume_24h:
                    continue
                if t.get('market_warning') == 'CAUTION':
                    continue
                if price <= 0:
                    continue

                # 모멘텀 스코어: 거래대금 × 상승률 (상승 중인 종목만)
                score = volume_24h * change_rate if change_rate > 0 else 0

                coin = t['market'].replace('KRW-', '')
                candidates.append({
                    'coin': coin,
                    'market': t['market'],
                    'price': price,
                    'change_pct': change_rate,
                    'volume_krw': volume_24h,
                    'score': score,
                })
            except Exception:
                continue

        candidates.sort(key=lambda x: x['score'], reverse=True)
        logger.info(f"전체 {len(markets)}개 종목 스캔 → {len(candidates)}개 필터 통과")
        return candidates[:top_n]

    # ===== 잔고 조회 =====

    def get_accounts(self) -> list:
        """전체 계좌 조회"""
        return self._private_get('/v1/accounts') or []

    def get_krw_balance(self) -> float:
        """원화 잔고"""
        try:
            accounts = self.get_accounts()
            if not isinstance(accounts, list):
                logger.warning(f"계좌 응답 비정상: {accounts}")
                return 0.0
            for acc in accounts:
                if not isinstance(acc, dict):
                    continue
                if acc.get('currency') == 'KRW':
                    return float(acc.get('balance', 0))
            return 0.0
        except Exception as e:
            logger.error(f"원화 잔고 조회 실패: {e}")
            return 0.0

    def get_coin_balance(self, coin: str) -> float:
        """코인 잔고"""
        try:
            accounts = self.get_accounts()
            if not isinstance(accounts, list):
                return 0.0
            for acc in accounts:
                if not isinstance(acc, dict):
                    continue
                if acc.get('currency') == coin:
                    return float(acc.get('balance', 0))
            return 0.0
        except Exception as e:
            logger.error(f"코인 잔고 조회 실패 [{coin}]: {e}")
            return 0.0

    # ===== 주문 =====

    def buy_market(self, coin: str, krw_amount: float) -> dict | None:
        """시장가 매수 (KRW 금액 기준)"""
        body = {
            'market': f'KRW-{coin}',
            'side': 'bid',
            'price': str(int(krw_amount)),
            'order_type': 'price',
        }
        result = self._private_post('/v2/orders', body)
        if result and ('order_id' in result or 'uuid' in result):
            oid = result.get('order_id') or result.get('uuid')
            logger.info(f"시장가 매수 [{coin}] {krw_amount:,.0f}원 → order_id={oid}")
        else:
            logger.error(f"시장가 매수 실패 [{coin}]: {result}")
            return None
        return result

    def sell_market(self, coin: str, quantity: float) -> dict | None:
        """시장가 매도 (수량 기준)"""
        body = {
            'market': f'KRW-{coin}',
            'side': 'ask',
            'volume': str(quantity),
            'order_type': 'market',
        }
        result = self._private_post('/v2/orders', body)
        if result and ('order_id' in result or 'uuid' in result):
            oid = result.get('order_id') or result.get('uuid')
            logger.info(f"시장가 매도 [{coin}] {quantity} → order_id={oid}")
        else:
            logger.error(f"시장가 매도 실패 [{coin}]: {result}")
            return None
        return result

    def buy_limit(self, coin: str, price: float, quantity: float) -> dict | None:
        """지정가 매수"""
        body = {
            'market': f'KRW-{coin}',
            'side': 'bid',
            'price': str(int(price)),
            'volume': str(quantity),
            'order_type': 'limit',
        }
        result = self._private_post('/v2/orders', body)
        if result and ('order_id' in result or 'uuid' in result):
            logger.info(f"지정가 매수 [{coin}] {price:,.0f}원 x {quantity}")
        else:
            logger.error(f"지정가 매수 실패 [{coin}]: {result}")
            return None
        return result

    def sell_limit(self, coin: str, price: float, quantity: float) -> dict | None:
        """지정가 매도"""
        body = {
            'market': f'KRW-{coin}',
            'side': 'ask',
            'price': str(int(price)),
            'volume': str(quantity),
            'order_type': 'limit',
        }
        result = self._private_post('/v2/orders', body)
        if result and ('order_id' in result or 'uuid' in result):
            logger.info(f"지정가 매도 [{coin}] {price:,.0f}원 x {quantity}")
        else:
            logger.error(f"지정가 매도 실패 [{coin}]: {result}")
            return None
        return result
