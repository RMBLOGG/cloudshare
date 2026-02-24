from flask import Flask, render_template, request, jsonify, redirect, session
import cloudinary
import cloudinary.uploader
import cloudinary.api
import cloudinary.utils
from supabase import create_client, Client
from datetime import datetime, timedelta
import random
import string
import time
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

# Cloudinary
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME', 'dzfkklsza')
CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY', '588474134734416')
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET', '9c12YJe5rZSYSg7zROQuvmVZ7mg')
cloudinary.config(cloud_name=CLOUDINARY_CLOUD_NAME, api_key=CLOUDINARY_API_KEY, api_secret=CLOUDINARY_API_SECRET)

# Supabase
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Admin
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'ganti-token-rahasia-ini')

# Payment info
PAYMENT_NUMBER = '082320781747'
SUBSCRIPTION_PRICE = 30000
DEFAULT_VIDEO_PRICE = 10000

def generate_id(k=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=k))

def get_file(file_id):
    result = supabase.table('cloudshare').select('*').eq('file_id', file_id).execute()
    return result.data[0] if result.data else None

def is_admin(token):
    return token == ADMIN_TOKEN

def has_access(email, file_id, access_type):
    """Cek apakah email punya akses ke file."""
    if not email:
        return False
    now = datetime.now().isoformat()
    # Cek langganan aktif
    if access_type in ('paid', 'premium'):
        sub = supabase.table('orders').select('*')\
            .eq('email', email).eq('type', 'subscription')\
            .eq('status', 'confirmed')\
            .gte('expires_at', now).execute()
        if sub.data:
            return True
    # Cek beli per video
    if access_type == 'paid':
        purchase = supabase.table('orders').select('*')\
            .eq('email', email).eq('file_id', file_id)\
            .eq('type', 'video').eq('status', 'confirmed').execute()
        if purchase.data:
            return True
    return False

# ============================================================
# PUBLIC ROUTES
# ============================================================

@app.route('/')
def index():
    result = supabase.table('cloudshare').select('*').order('uploaded_at', desc=True).execute()
    files = [(row['file_id'], row) for row in result.data if not row.get('blocked')]
    return render_template('index.html', files=files)

@app.route('/<file_id>')
def view_file(file_id):
    reserved = ['gallery', 'upload', 'sign-upload', 'save-upload', 'admin-api', 'order', 'subscribe', 'check-access']
    if file_id in reserved:
        return redirect('/')

    file_data = get_file(file_id)
    if not file_data:
        return render_template('error.html', error="File tidak ditemukan"), 404
    if file_data.get('blocked'):
        return render_template('error.html', error="File ini tidak tersedia"), 403

    access_type = file_data.get('access_type', 'free')

    # Password check
    if file_data.get('password'):
        if not session.get(f'auth_{file_id}'):
            return render_template('password.html', file_id=file_id)

    # Akses berbayar
    if access_type in ('paid', 'premium'):
        email = session.get('user_email')
        if not has_access(email, file_id, access_type):
            return render_template('paywall.html',
                file_data=file_data,
                file_id=file_id,
                access_type=access_type,
                price=file_data.get('price', DEFAULT_VIDEO_PRICE),
                subscription_price=SUBSCRIPTION_PRICE,
                payment_number=PAYMENT_NUMBER,
            )

    return render_template('view.html', file_data=file_data, file_id=file_id)

@app.route('/<file_id>/verify', methods=['POST'])
def verify_password(file_id):
    file_data = get_file(file_id)
    if not file_data:
        return jsonify({'success': False, 'error': 'File not found'})
    password = request.json.get('password', '')
    if file_data.get('password') == password:
        session[f'auth_{file_id}'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Incorrect password'})

@app.route('/sign-upload', methods=['POST'])
def sign_upload():
    try:
        file_id = generate_id()
        timestamp = int(time.time())
        public_id = f"cloudshare/cloudshare_{timestamp}_{file_id}"
        params_to_sign = {'public_id': public_id, 'timestamp': timestamp}
        signature = cloudinary.utils.api_sign_request(params_to_sign, CLOUDINARY_API_SECRET)
        return jsonify({'success': True, 'signature': signature, 'timestamp': timestamp,
                        'public_id': public_id, 'api_key': CLOUDINARY_API_KEY,
                        'cloud_name': CLOUDINARY_CLOUD_NAME, 'file_id': file_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/save-upload', methods=['POST'])
def save_upload():
    try:
        data = request.json
        file_id = data.get('file_id')
        title = data.get('title', '').strip()
        description = data.get('description', '').strip()
        password = data.get('password', '').strip()
        access_type = data.get('access_type', 'free')
        price = int(data.get('price', DEFAULT_VIDEO_PRICE))
        row = {
            'file_id': file_id,
            'cloudinary_url': data.get('secure_url'),
            'public_id': data.get('public_id'),
            'format': data.get('format'),
            'resource_type': data.get('resource_type'),
            'bytes': data.get('bytes'),
            'original_filename': data.get('original_filename'),
            'uploaded_at': datetime.now().isoformat(),
            'width': data.get('width'),
            'height': data.get('height'),
            'duration': data.get('duration'),
            'title': title if title else data.get('original_filename', 'Untitled'),
            'description': description if description else None,
            'password': password if password else None,
            'blocked': False,
            'access_type': access_type,
            'price': price,
        }
        supabase.table('cloudshare').insert(row).execute()
        base_url = request.host_url.rstrip('/')
        return jsonify({'success': True, 'file_id': file_id, 'url': f"{base_url}/{file_id}",
                        'format': data.get('format'), 'resource_type': data.get('resource_type'),
                        'bytes': data.get('bytes')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ============================================================
# PAYMENT ROUTES
# ============================================================

@app.route('/order', methods=['POST'])
def create_order():
    """User submit order (per video atau langganan)."""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        name = data.get('name', '').strip()
        order_type = data.get('type', 'video')  # 'video' atau 'subscription'
        file_id = data.get('file_id')
        payment_method = data.get('payment_method', 'dana')

        if not email:
            return jsonify({'success': False, 'error': 'Email wajib diisi'})

        if order_type == 'video':
            file_data = get_file(file_id)
            if not file_data:
                return jsonify({'success': False, 'error': 'File tidak ditemukan'})
            amount = file_data.get('price', DEFAULT_VIDEO_PRICE)
        else:
            amount = SUBSCRIPTION_PRICE

        order_id = 'ORD-' + generate_id(10).upper()
        expires_at = (datetime.now() + timedelta(days=30)).isoformat() if order_type == 'subscription' else None

        row = {
            'order_id': order_id,
            'file_id': file_id,
            'email': email,
            'name': name,
            'amount': amount,
            'type': order_type,
            'status': 'pending',
            'payment_method': payment_method,
            'created_at': datetime.now().isoformat(),
            'expires_at': expires_at,
        }
        supabase.table('orders').insert(row).execute()

        # Simpan email ke session
        session['user_email'] = email
        session['pending_order'] = order_id

        return jsonify({'success': True, 'order_id': order_id, 'amount': amount,
                        'payment_number': PAYMENT_NUMBER, 'payment_method': payment_method})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/upload-proof', methods=['POST'])
def upload_proof():
    """Upload bukti transfer ke Cloudinary."""
    try:
        order_id = request.form.get('order_id')
        if 'proof' not in request.files:
            return jsonify({'success': False, 'error': 'Tidak ada file'})

        file = request.files['proof']
        result = cloudinary.uploader.upload(
            file,
            folder='cloudshare_proofs',
            resource_type='image',
        )
        proof_url = result['secure_url']
        supabase.table('orders').update({'proof_url': proof_url}).eq('order_id', order_id).execute()
        return jsonify({'success': True, 'proof_url': proof_url})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/check-access', methods=['POST'])
def check_access():
    """Cek apakah email sudah punya akses setelah dikonfirmasi admin."""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        file_id = data.get('file_id')
        file_data = get_file(file_id)
        if not file_data:
            return jsonify({'success': False})
        access_type = file_data.get('access_type', 'free')
        session['user_email'] = email
        if has_access(email, file_id, access_type):
            return jsonify({'success': True, 'redirect': f'/{file_id}'})
        return jsonify({'success': False, 'message': 'Pembayaran belum dikonfirmasi admin'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ============================================================
# ADMIN ROUTES
# ============================================================

@app.route('/<token>/admin')
def admin_panel(token):
    if not is_admin(token):
        return render_template('error.html', error="Halaman tidak ditemukan"), 404

    result = supabase.table('cloudshare').select('*').order('uploaded_at', desc=True).execute()
    all_files = result.data

    # Orders pending
    orders_result = supabase.table('orders').select('*').order('created_at', desc=True).execute()
    all_orders = orders_result.data
    pending_orders = [o for o in all_orders if o['status'] == 'pending']

    total = len(all_files)
    total_bytes = sum(f.get('bytes', 0) or 0 for f in all_files)
    videos = sum(1 for f in all_files if f.get('resource_type') == 'video')
    locked = sum(1 for f in all_files if f.get('password'))
    total_revenue = sum(o.get('amount', 0) for o in all_orders if o['status'] == 'confirmed')

    def fmt_storage(b):
        if b >= 1024**3: return f"{b/1024**3:.1f} GB"
        if b >= 1024**2: return f"{b/1024**2:.1f} MB"
        return f"{b/1024:.1f} KB"

    def fmt_rupiah(n):
        return f"Rp {n:,.0f}".replace(',', '.')

    stats = {
        'total': total,
        'storage': fmt_storage(total_bytes),
        'videos': videos,
        'locked': locked,
        'pending_orders': len(pending_orders),
        'revenue': fmt_rupiah(total_revenue),
    }

    today = datetime.now().date()
    day_counts = {}
    for f in all_files:
        try:
            d = datetime.fromisoformat(f['uploaded_at'][:10]).date()
            day_counts[d] = day_counts.get(d, 0) + 1
        except:
            pass

    chart_data = []
    max_count = max(day_counts.values(), default=1) or 1
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        count = day_counts.get(d, 0)
        chart_data.append({'label': d.strftime('%d/%m'), 'count': count,
                           'pct': max(4, int(count / max_count * 100))})

    files = [(row['file_id'], row) for row in all_files]
    return render_template('admin.html',
        files=files, stats=stats, chart_data=chart_data,
        admin_token=token, orders=all_orders, pending_orders=pending_orders,
        default_video_price=DEFAULT_VIDEO_PRICE,
        subscription_price=SUBSCRIPTION_PRICE,
    )

@app.route('/<token>/logout')
def admin_logout(token):
    return redirect('/')

# ============================================================
# ADMIN API
# ============================================================

@app.route('/admin-api/edit', methods=['POST'])
def admin_edit():
    data = request.json
    if not is_admin(data.get('token')):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    try:
        file_id = data.get('file_id')
        update = {
            'title': data.get('title') or 'Untitled',
            'description': data.get('description') or None,
            'password': data.get('password') or None,
            'access_type': data.get('access_type', 'free'),
            'price': int(data.get('price', DEFAULT_VIDEO_PRICE)),
        }
        supabase.table('cloudshare').update(update).eq('file_id', file_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin-api/delete', methods=['POST'])
def admin_delete():
    data = request.json
    if not is_admin(data.get('token')):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    try:
        file_id = data.get('file_id')
        file_data = get_file(file_id)
        if not file_data:
            return jsonify({'success': False, 'error': 'File tidak ditemukan'})
        try:
            cloudinary.uploader.destroy(file_data['public_id'], resource_type=file_data.get('resource_type', 'image'))
        except:
            pass
        supabase.table('cloudshare').delete().eq('file_id', file_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin-api/block', methods=['POST'])
def admin_block():
    data = request.json
    if not is_admin(data.get('token')):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    try:
        supabase.table('cloudshare').update({'blocked': data.get('blocked', True)}).eq('file_id', data.get('file_id')).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin-api/confirm-order', methods=['POST'])
def admin_confirm_order():
    """Admin konfirmasi pembayaran."""
    data = request.json
    if not is_admin(data.get('token')):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    try:
        order_id = data.get('order_id')
        action = data.get('action', 'confirm')  # 'confirm' atau 'reject'
        update = {
            'status': 'confirmed' if action == 'confirm' else 'rejected',
            'confirmed_at': datetime.now().isoformat() if action == 'confirm' else None,
        }
        supabase.table('orders').update(update).eq('order_id', order_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True)
