from flask import Flask, render_template, request, jsonify, redirect, session
import cloudinary
import cloudinary.uploader
import cloudinary.api
import cloudinary.utils
from supabase import create_client, Client
from datetime import datetime
import random
import string
import hashlib
import time
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB untuk request biasa (bukan upload file)

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

# Generate random ID for uploads
def generate_id():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

# Helper: get file by file_id
def get_file(file_id):
    result = supabase.table('cloudshare').select('*').eq('file_id', file_id).execute()
    return result.data[0] if result.data else None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/gallery')
def gallery():
    result = supabase.table('cloudshare').select('*').order('uploaded_at', desc=True).execute()
    files = [(row['file_id'], row) for row in result.data]
    return render_template('gallery.html', files=files)

@app.route('/<file_id>')
def view_file(file_id):
    # Hindari konflik dengan route lain
    if file_id in ['gallery', 'upload', 'sign-upload', 'save-upload']:
        return redirect('/')

    file_data = get_file(file_id)
    
    if not file_data:
        return render_template('error.html', error="File not found"), 404
    
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

# =============================================
# ENDPOINT BARU: Generate signature untuk upload langsung dari browser
# =============================================
@app.route('/sign-upload', methods=['POST'])
def sign_upload():
    try:
        file_id = generate_id()
        timestamp = int(time.time())
        public_id = f"cloudshare/cloudshare_{timestamp}_{file_id}"

        # Params yang akan di-sign
        params_to_sign = {
            'public_id': public_id,
            'timestamp': timestamp,
        }

        # Generate signature
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

# =============================================
# ENDPOINT BARU: Simpan metadata setelah upload berhasil di browser
# =============================================
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
        }

        supabase.table('cloudshare').insert(row).execute()

        base_url = request.host_url.rstrip('/')
        share_url = f"{base_url}/{file_id}"

        return jsonify({
            'success': True,
            'file_id': file_id,
            'url': share_url,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True)
