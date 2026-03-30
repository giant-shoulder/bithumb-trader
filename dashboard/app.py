"""
빗썸 자동매매 모니터링 대시보드
"""
import subprocess
import os
import csv
import glob
from datetime import datetime, date
from functools import wraps
from flask import Flask, render_template, Response, request, session, redirect, url_for, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get('DASHBOARD_SECRET', 'bithumb-dashboard-secret')
DASHBOARD_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', 'admin1234')


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == DASHBOARD_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        return render_template('login.html', error='비밀번호가 틀렸습니다')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    return render_template('index.html')


@app.route('/api/status')
@login_required
def status():
    result = subprocess.run(
        ['sudo', 'systemctl', 'is-active', 'bithumb-trader'],
        capture_output=True, text=True
    )
    return jsonify({'status': result.stdout.strip()})


@app.route('/api/control/<action>', methods=['POST'])
@login_required
def control(action):
    if action not in ['start', 'stop', 'restart']:
        return jsonify({'error': 'invalid action'}), 400
    subprocess.run(['sudo', 'systemctl', action, 'bithumb-trader'])
    return jsonify({'ok': True})


@app.route('/api/logs')
@login_required
def logs():
    def generate():
        process = subprocess.Popen(
            ['sudo', 'journalctl', '-u', 'bithumb-trader', '-f', '-n', '200', '--no-pager', '--output=short'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        for line in process.stdout:
            yield f"data: {line.rstrip()}\n\n"
    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/review')
@app.route('/review/<target_date>')
@login_required
def review(target_date=None):
    if target_date is None:
        target_date = date.today().strftime('%Y-%m-%d')
    return render_template('review.html', target_date=target_date)


@app.route('/api/review/<target_date>')
@login_required
def review_data(target_date):
    base_dir = '/home/ubuntu/bithumb-trader'
    ym = target_date[:7].replace('-', '')

    # 매매 기록 읽기
    trades = []
    trade_file = f"{base_dir}/trade_history_{ym}.csv"
    if os.path.exists(trade_file):
        with open(trade_file, encoding='utf-8') as f:
            reader = csv.DictReader(f, restkey=None)
            for row in reader:
                if row['시간'].startswith(target_date):
                    row.pop(None, None)
                    trades.append(row)

    # 탈락 기록 읽기
    rejects = []
    reject_file = f"{base_dir}/reject_history_{ym}.csv"
    if os.path.exists(reject_file):
        with open(reject_file, encoding='utf-8') as f:
            reader = csv.DictReader(f, restkey=None)
            for row in reader:
                if row['시간'].startswith(target_date):
                    row.pop(None, None)
                    rejects.append(row)

    # 통계 계산
    buys = [t for t in trades if t['유형'] == '매수']
    sells = [t for t in trades if t['유형'] == '매도']
    wins = [t for t in sells if float(t['손익률']) > 0]
    losses = [t for t in sells if float(t['손익률']) <= 0]
    total_pnl = sum(float(t['손익률']) for t in sells)

    # 실제 손익(원) 계산: 매도금액이 아닌 매수금액 기준으로 계산
    # 매수금액 = 매도금액 / (1 + 손익률/100)
    def calc_pnl_krw(t):
        pnl_pct = float(t['손익률'])
        sell_amt = float(t['금액'])
        buy_amt = sell_amt / (1 + pnl_pct / 100)
        return buy_amt * pnl_pct / 100

    pnl_krw = sum(calc_pnl_krw(t) for t in sells)
    total_invested = sum(float(t['금액']) / (1 + float(t['손익률']) / 100) for t in sells)
    portfolio_return_pct = pnl_krw / total_invested * 100 if total_invested else 0

    # 신호 출처별 통계
    sources = {}
    for t in sells:
        src = t.get('신호출처', 'momentum')
        if src not in sources:
            sources[src] = {'count': 0, 'wins': 0, 'pnl': 0.0}
        sources[src]['count'] += 1
        sources[src]['pnl'] += float(t['손익률'])
        if float(t['손익률']) > 0:
            sources[src]['wins'] += 1

    return jsonify({
        'date': target_date,
        'trades': trades,
        'rejects': rejects,
        'stats': {
            'buy_count': len(buys),
            'sell_count': len(sells),
            'win_count': len(wins),
            'loss_count': len(losses),
            'win_rate': len(wins) / len(sells) * 100 if sells else 0,
            'total_pnl_pct': portfolio_return_pct,
            'total_pnl_krw': pnl_krw,
            'total_pnl_pct_sum': total_pnl,
            'avg_win': sum(float(t['손익률']) for t in wins) / len(wins) if wins else 0,
            'avg_loss': sum(float(t['손익률']) for t in losses) / len(losses) if losses else 0,
        },
        'sources': sources,
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
