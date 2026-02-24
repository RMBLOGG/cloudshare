from flask import Flask, render_template, request, jsonify, redirect, session
import cloudinary
import cloudinary.uploader
import cloudinary.api
from supabase import create_client, Client
from datetime import datetime
import random
import string
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')

# Cloudinary Configuration
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', 'dzfkklsza'),
    api_key=os.environ.get('CLOUDINARY_API_KEY', '588474134734416'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET', '9c12YJe5rZSYSg7zROQuvmVZ7mg')
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
    file_data = get_file(file_id)
    
    if not file_data:
        return render_template('error.html', error="File not found"), 404
    
    # Check if password protected
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

@app.route('/upload', methods=['POST'])
def upload():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'})
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})
        
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        password = request.form.get('password', '').strip()
        
        # Generate unique ID
        file_id = generate_id()
        
        # Upload to Cloudinary
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        public_id = f"cloudshare_{timestamp}_{file_id}"
        
        upload_result = cloudinary.uploader.upload(
            file,
            public_id=public_id,
            resource_type='auto',
            folder='cloudshare'
        )
        
        # Simpan ke Supabase
        row = {
            'file_id': file_id,
            'cloudinary_url': upload_result['secure_url'],
            'public_id': upload_result['public_id'],
            'format': upload_result['format'],
            'resource_type': upload_result['resource_type'],
            'bytes': upload_result['bytes'],
            'original_filename': file.filename,
            'uploaded_at': datetime.now().isoformat(),
            'width': upload_result.get('width'),
            'height': upload_result.get('height'),
            'duration': upload_result.get('duration'),
            'title': title if title else file.filename,
            'description': description if description else None,
            'password': password if password else None,
        }
        supabase.table('cloudshare').insert(row).execute()
        
        # Return share URL
        base_url = request.host_url.rstrip('/')
        share_url = f"{base_url}/{file_id}"
        
        return jsonify({
            'success': True,
            'file_id': file_id,
            'url': share_url,
            'format': upload_result['format'],
            'resource_type': upload_result['resource_type'],
            'bytes': upload_result['bytes']
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True)
