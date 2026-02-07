from flask import Flask, render_template, request, jsonify, redirect, session
import cloudinary
import cloudinary.uploader
import cloudinary.api
from datetime import datetime
import random
import string
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'  # Change this!

# Cloudinary Configuration
cloudinary.config(
    cloud_name="dzfkklsza",
    api_key="588474134734416",
    api_secret="9c12YJe5rZSYSg7zROQuvmVZ7mg"
)

# Simple in-memory database (untuk production gunakan database real)
uploads_db = {}

# Generate random ID for uploads
def generate_id():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/gallery')
def gallery():
    # Sort by upload date, newest first
    sorted_files = sorted(
        uploads_db.items(), 
        key=lambda x: x[1]['uploaded_at'], 
        reverse=True
    )
    return render_template('gallery.html', files=sorted_files)

@app.route('/<file_id>')
def view_file(file_id):
    if file_id not in uploads_db:
        return render_template('error.html', error="File not found"), 404
    
    file_data = uploads_db[file_id]
    
    # Check if password protected
    if file_data.get('password'):
        # Check if already authenticated in session
        if not session.get(f'auth_{file_id}'):
            return render_template('password.html', file_id=file_id)
    
    return render_template('view.html', file_data=file_data, file_id=file_id)

@app.route('/<file_id>/verify', methods=['POST'])
def verify_password(file_id):
    if file_id not in uploads_db:
        return jsonify({'success': False, 'error': 'File not found'})
    
    file_data = uploads_db[file_id]
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
        
        # Get title, description, and password from form
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        password = request.form.get('password', '').strip()
        
        # Generate unique ID untuk website
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
        
        # Simpan data ke database
        uploads_db[file_id] = {
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
            'description': description,
            'password': password if password else None
        }
        
        # Return URL website, bukan Cloudinary
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
