# 빗썸 자동매매 - 홍인기 단타 전략

## 핵심 원칙

1. **거래대금 1등 코인만 매수** - 거래대금 상위 코인 중 상승률 1위
2. **정배열 확인 필수** - MA5 > MA20 > MA60 > MA120
3. **장대양봉 돌파 매수** - 전고점 돌파 + 거래대금 급증
4. **불타기** - 최대 한도의 1/5씩 최대 5번 분할 매수
5. **손절 -1%** - 매입단가 대비 1% 하락 시 무조건 손절
6. **초단타 매도 전략** - 트레일링 스탑 / RSI 과매수 반전 / 볼린저밴드 상단 / MACD 데드크로스

## 매수 조건 (모두 충족 시)

- [ ] 거래대금 상위 5위 이내
- [ ] 24시간 상승률 5% 이상
- [ ] 정배열 (MA5 > MA20 > MA60)
- [ ] 최근 캔들이 장대양봉 (시가 대비 3% 이상 상승 마감)
- [ ] 6개월 내 전고점 돌파 중

## 매도 조건

- 손절: 매입가 대비 -1%
- 트레일링 스탑: +0.8% 수익 시 활성화 → 고점 대비 -0.4% 하락 시 매도
- RSI > 72 후 하락 반전
- 볼린저 밴드 상단 터치
- MACD 데드크로스
- 대장 코인 교체 (거래대금 10위 밖)

## 파일 구조

- `config.py`: API 키, 전략 파라미터 설정값
- `bithumb_api.py`: 빗썸 REST API 래퍼
- `strategy.py`: 홍인기 전략 + 초단타 매도 로직 (RSI/BB/MACD/트레일링스탑)
- `trader.py`: 자동매매 실행 루프, Position 관리
- `logger.py`: 거래 로그
- `main.py`: 진입점
- `bithumb_api_docs.pdf`: 빗썸 API 레퍼런스 전체 (76페이지)

---

## 빗썸 API 레퍼런스 요약

> 원본: `bithumb_api_docs.pdf` (apidocs.bithumb.com)

### 기본 정보

- **REST Base URL**: `https://api.bithumb.com`
- **API 버전**: v1 (조회), v2 (주문)
- **마켓 코드 형식**: `KRW-BTC`, `KRW-ETH` 등 (항상 대문자)
- **Content-Type**: `application/json; charset=utf-8`

### 인증 (JWT)

Private API는 JWT 토큰을 `Authorization: Bearer {token}` 헤더로 전달.

```python
import jwt, uuid, time

payload = {
    'access_key': ACCESS_KEY,
    'nonce': str(uuid.uuid4()),
    'timestamp': round(time.time() * 1000),
    # 쿼리 파라미터 있을 경우:
    # 'query_hash': SHA512(query_string),
    # 'query_hash_alg': 'SHA512'
}
token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')
headers = {'Authorization': f'Bearer {token}'}
```

파라미터가 있는 경우 `query_hash` 필수:
```python
import hashlib, urllib

query_string = urllib.parse.urlencode(params).encode()
query_hash = hashlib.sha512(query_string).hexdigest()
payload['query_hash'] = query_hash
payload['query_hash_alg'] = 'SHA512'
```

### 요청 제한 (Rate Limit)

| 구분 | 초당 최대 요청 수 |
|------|-----------------|
| Public API | 150회 |
| Private API | 140회 |
| 주문 생성/취소 | **10회** (별도 제한) |

초과 시 일시적 제한 → 자동 해제까지 대기 필요.

---

### Public API (인증 불필요)

#### 마켓 코드 조회
```
GET /v1/market/all
Query: isDetails=false (선택)
Response: [{market, korean_name, english_name, market_warning}]
market_warning: NONE | CAUTION
```

#### 분봉 캔들
```
GET /v1/candles/minutes/{unit}
unit: 1, 3, 5, 10, 15, 30, 60, 240
Query: market(필수), to(마지막시간 ISO8061), count(최대200)
Response: [{market, candle_date_time_utc, candle_date_time_kst,
            opening_price, high_price, low_price, trade_price,
            timestamp, candle_acc_trade_price, candle_acc_trade_volume}]
```

#### 일봉/주봉/월봉 캔들
```
GET /v1/candles/days
GET /v1/candles/weeks
GET /v1/candles/months
Query: market(필수), to, count(최대200), convertingPriceUnit
```

#### 현재가 (Ticker)
```
GET /v1/ticker
Query: markets=KRW-BTC,KRW-ETH (콤마 구분)
Response: [{market, trade_date, trade_time, trade_date_kst, trade_time_kst,
            trade_timestamp, opening_price, high_price, low_price, trade_price,
            prev_closing_price, change(RISE/FALL/EVEN), change_price, change_rate,
            signed_change_price, signed_change_rate, trade_volume,
            acc_trade_price, acc_trade_price_24h,
            acc_trade_volume, acc_trade_volume_24h,
            highest_52_week_price, lowest_52_week_price, timestamp}]
```

#### 호가 (Orderbook)
```
GET /v1/orderbook
Query: markets=KRW-BTC (콤마 구분), level(호가 묶음 단위, 선택)
Response: [{market, timestamp, total_ask_size, total_bid_size,
            orderbook_units: [{ask_price, bid_price, ask_size, bid_size}]}]
```

#### 체결 내역
```
GET /v1/trades/ticks
Query: market(필수), to, count(최대500), cursor, daysAgo(최대7)
Response: [{market, trade_date_utc, trade_time_utc, timestamp,
            trade_price, trade_volume, prev_closing_price,
            change_price, ask_bid(ASK/BID), sequential_id}]
```

#### 투자유의 종목
```
GET /v1/market/caution
Query: markets (콤마 구분, 선택)
```

---

### Private API (JWT 인증 필요)

#### 전체 계좌 조회
```
GET /v1/accounts
Response: [{currency, balance, locked, avg_buy_price,
            avg_buy_price_modified, unit_currency}]
- balance: 주문 가능 수량
- locked: 주문에 묶인 수량
- avg_buy_price: 매수 평균가
```

#### 주문 가능 정보
```
GET /v1/orders/chance
Query: market(필수)
Response: {bid_fee, ask_fee, maker_bid_fee, maker_ask_fee,
           market{id, name, order_types, order_sides, bid, ask, max_total, state},
           bid_account, ask_account}
```

#### 주문 요청 ⭐
```
POST /v2/orders
Body (JSON):
  market*: string       마켓코드 (예: KRW-BTC)
  side*: bid|ask        bid=매수, ask=매도
  order_type*: limit|price|market
    - limit: 지정가 (price + volume 필수)
    - price: 시장가 매수 (price=총금액 필수)
    - market: 시장가 매도 (volume=수량 필수)
  price: string         주문 가격 (지정가/시장가매수 필수)
  volume: string        주문 수량 (지정가/시장가매도 필수)
  client_order_id: string  사용자 지정 주문 ID (선택, 영문/숫자/-/_ 1~36자)

Response: {uuid, side, order_type, price, state, market, created_at,
           volume, remaining_volume, reserved_fee, remaining_fee,
           paid_fee, locked, executed_volume, trade_count}
```

#### 주문 취소
```
DELETE /v2/order
Query: order_id 또는 client_order_ids (둘 중 하나 필수)
       order_id와 client_order_ids 둘 다 전달 시 order_id 우선
```

#### 개별 주문 조회
```
GET /v1/order
Query: uuid(order_id) 또는 identifier(client_order_id)
```

#### 주문 목록 조회
```
GET /v1/orders/open  (미체결)
GET /v1/orders/closed  (완료/취소)
Query: market, state, page, limit(최대100), order_by(asc/desc)
```

#### 다중 주문 요청
```
POST /v1/orders/bulk
Body: {orders: [{market, side, volume, price, order_type, client_order_id}]}
```

#### 다중 주문 취소
```
DELETE /v1/orders/bulk
Body: {order_ids: [...]} 또는 {client_order_ids: [...]}
```

---

### WebSocket API

**URL**: `wss://api.bithumb.com/websocket/v1`

요청 형식:
```json
[
  {"ticket": "unique-ticket-id"},
  {"type": "ticker", "codes": ["KRW-BTC", "KRW-ETH"], "isOnlyRealtime": true},
  {"format": "DEFAULT"}
]
```

| type | 설명 |
|------|------|
| `ticker` | 현재가 (스냅샷+실시간) |
| `trade` | 체결 내역 |
| `orderbook` | 호가 |
| `myOrder` | 내 주문/체결 (인증 필요) |
| `myAsset` | 내 자산 (인증 필요) |

- `isOnlySnapshot: true`: 스냅샷만
- `isOnlyRealtime: true`: 실시간만
- 둘 다 생략: 스냅샷 + 실시간 모두

---

### 주요 에러 코드

| HTTP | 코드 | 설명 |
|------|------|------|
| 400 | `invalid_parameter` | 잘못된 파라미터 |
| 400 | `invalid_price` | 잘못된 주문 가격 단위 |
| 400 | `under_price_limit_ask/bid` | 최소 주문 가격 미달 |
| 400 | `bank_account_required` | 실명 계좌 미등록 |
| 401 | `two_factor_auth_required` | 인증 채널 오류 |

---

### pybithumb 사용 시 참고

현재 프로젝트는 `pybithumb` 라이브러리를 사용하지만, 해당 라이브러리가 구버전 API를 일부 사용할 수 있음.
주문 관련 기능은 직접 REST API(`/v2/orders`) 호출을 권장.
