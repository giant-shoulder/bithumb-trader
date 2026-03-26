"""
빗썸 자동매매 모니터링 대시보드
"""
import subprocess
import os
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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
