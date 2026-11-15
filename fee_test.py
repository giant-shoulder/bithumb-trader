"""수수료 쿠폰 적용 검증용 1회성 테스트 매매
ETH 6,000원 시장가 매수 → 체결 확인 → 전량 시장가 매도 → 양쪽 paid_fee 판독
0.04% 적용 시 왕복 수수료 ~5원, 0.25%면 ~30원
"""
import time
import json
from bithumb_api import BithumbAPI

api = BithumbAPI()


def wait_done(uid):
    o = None
    for _ in range(30):
        o = api.get_order(uid)
        if o and o.get("state") in ("done", "cancel") and float(o.get("executed_volume") or 0) > 0:
            return o
        time.sleep(0.5)
    return o


buy = api.buy_market("ETH", 6000)
if not buy:
    raise SystemExit("매수 주문 실패")
o = wait_done(buy.get("uuid") or buy.get("order_id"))
ev = o.get("executed_volume")
funds = float(o.get("executed_funds") or 0)
pf = float(o.get("paid_fee") or 0)
print("BUY :", json.dumps({k: o.get(k) for k in ("state", "executed_volume", "executed_funds", "paid_fee")}, ensure_ascii=False))
print(f"매수 수수료율: {pf / funds * 100:.4f}%" if funds else "매수 체결 확인 실패")

sell = api.sell_market("ETH", ev)
if not sell:
    bal = api.get_coin_balance("ETH")
    print("전량 매도 실패, 보유량으로 재시도:", bal)
    sell = api.sell_market("ETH", bal)
    if not sell:
        raise SystemExit("매도 주문 실패 - ETH 잔고 수동 확인 필요!")
s = wait_done(sell.get("uuid") or sell.get("order_id"))
sfunds = float(s.get("executed_funds") or 0)
spf = float(s.get("paid_fee") or 0)
print("SELL:", json.dumps({k: s.get(k) for k in ("state", "executed_volume", "executed_funds", "paid_fee")}, ensure_ascii=False))
print(f"매도 수수료율: {spf / sfunds * 100:.4f}%" if sfunds else "매도 체결 확인 실패")
print(f"수수료 합계: {pf + spf:.1f}원 | 왕복 손익: {sfunds - spf - funds - pf:+.1f}원")
