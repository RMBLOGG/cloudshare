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

# Cloudinary Configuration
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME', 'dzfkklsza')
CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY', '588474134734416')
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET', '9c12YJe5rZSYSg7zROQuvmVZ7mg')

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET
)

# Supabase Configuration
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================
# ADMIN TOKEN — ganti dengan token rahasia kamu!
# Akses admin via: /ADMIN_TOKEN/admin
# ============================
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'ganti-token-rahasia-ini')

def generate_id():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

def get_file(file_id):
    result = supabase.table('cloudshare').select('*').eq('file_id', file_id).execute()
    return result.data[0] if result.data else None

def is_admin(token):
    return token == ADMIN_TOKEN

# ============================================================
# PUBLIC ROUTES
# ============================================================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/gallery')
def gallery():
    result = supabase.table('cloudshare').select('*').order('uploaded_at', desc=True).execute()
    files = [(row['file_id'], row) for row in result.data if not row.get('blocked')]
    return render_template('gallery.html', files=files)

@app.route('/<file_id>')
def view_file(file_id):
    reserved = ['gallery', 'upload', 'sign-upload', 'save-upload', 'admin-api']
    if file_id in reserved:
        return redirect('/')

    # Cek apakah ini route admin: /<token>/admin
    # Ditangani di route terpisah di bawah
    file_data = get_file(file_id)
    if not file_data:
        return render_template('error.html', error="File not found"), 404

    # Blokir file
    if file_data.get('blocked'):
        return render_template('error.html', error="File ini tidak tersedia"), 403

    if file_data.get('password'):
        if not session.get(f'auth_{file_id}'):
            return render_template('password.html', file_id=file_id)

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
    else:
        return jsonify({'success': False, 'error': 'Incorrect password'})

@app.route('/sign-upload', methods=['POST'])
def sign_upload():
    try:
        file_id = generate_id()
        timestamp = int(time.time())
        public_id = f"cloudshare/cloudshare_{timestamp}_{file_id}"
        params_to_sign = {'public_id': public_id, 'timestamp': timestamp}
        signature = cloudinary.utils.api_sign_request(params_to_sign, CLOUDINARY_API_SECRET)
        return jsonify({
            'success': True,
            'signature': signature,
            'timestamp': timestamp,
            'public_id': public_id,
            'api_key': CLOUDINARY_API_KEY,
            'cloud_name': CLOUDINARY_CLOUD_NAME,
            'file_id': file_id,
        })
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
        }
        supabase.table('cloudshare').insert(row).execute()
        base_url = request.host_url.rstrip('/')
        share_url = f"{base_url}/{file_id}"
        return jsonify({'success': True, 'file_id': file_id, 'url': share_url,
                        'format': data.get('format'), 'resource_type': data.get('resource_type'),
                        'bytes': data.get('bytes')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ============================================================
# ADMIN ROUTES — akses via /<ADMIN_TOKEN>/admin
# ============================================================

@app.route('/<token>/admin')
def admin_panel(token):
    if not is_admin(token):
        return render_template('error.html', error="Halaman tidak ditemukan"), 404

    result = supabase.table('cloudshare').select('*').order('uploaded_at', desc=True).execute()
    all_files = result.data

    # Stats
    total = len(all_files)
    total_bytes = sum(f.get('bytes', 0) or 0 for f in all_files)
    videos = sum(1 for f in all_files if f.get('resource_type') == 'video')
    locked = sum(1 for f in all_files if f.get('password'))

    def fmt_storage(b):
        if b >= 1024**3: return f"{b/1024**3:.1f} GB"
        if b >= 1024**2: return f"{b/1024**2:.1f} MB"
        return f"{b/1024:.1f} KB"

    stats = {
        'total': total,
        'storage': fmt_storage(total_bytes),
        'videos': videos,
        'locked': locked,
    }

    # Chart: upload per hari 14 hari terakhir
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
        chart_data.append({
            'label': d.strftime('%d/%m'),
            'count': count,
            'pct': max(4, int(count / max_count * 100)),
        })

    files = [(row['file_id'], row) for row in all_files]
    return render_template('admin.html',
        files=files,
        stats=stats,
        chart_data=chart_data,
        admin_token=token,
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
        # Hapus dari Cloudinary
        try:
            cloudinary.uploader.destroy(
                file_data['public_id'],
                resource_type=file_data.get('resource_type', 'image')
            )
        except:
            pass
        # Hapus dari Supabase
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
        file_id = data.get('file_id')
        blocked = data.get('blocked', True)
        supabase.table('cloudshare').update({'blocked': blocked}).eq('file_id', file_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True)
