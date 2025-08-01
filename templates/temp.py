# app.py
import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import pdfplumber
from docx import Document
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message # For email sending

# --- Flask App Configuration ---
app = Flask(_name_)
app.secret_key = 'your_strong_random_secret_key_here_change_in_production_really!' # CHANGE THIS IN PRODUCTION
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db' # SQLite database file
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- UPLOAD FOLDER CONFIGURATION ---
# Ensure UPLOAD_FOLDER is at the root level relative to app.py
# and contains subdirectories for resumes and jds
BASE_DIR = os.path.abspath(os.path.dirname(_file_))
UPLOAD_FOLDER_ROOT = os.path.join(BASE_DIR, 'uploads')
app.config['UPLOAD_FOLDER_RESUMES'] = os.path.join(UPLOAD_FOLDER_ROOT, 'resumes')
app.config['UPLOAD_FOLDER_JDS'] = os.path.join(UPLOAD_FOLDER_ROOT, 'jds')

# Create upload directories if they don't exist
os.makedirs(app.config['UPLOAD_FOLDER_RESUMES'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER_JDS'], exist_ok=True)


# --- Flask-Mail Configuration ---
# You need to set these environment variables or hardcode them (less secure for production)
# For Gmail, you'll need an App Password: https://support.google.com/accounts/answer/185833
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('EMAIL_USER') or 'masterpiece2124@gmail.com' # Replace with your email
app.config['MAIL_PASSWORD'] = os.environ.get('EMAIL_PASS') or 'uwhb seyn rbkj bser' # Replace with your App Password
app.config['MAIL_DEFAULT_SENDER'] = app.config['MAIL_USERNAME']


db = SQLAlchemy(app)
mail = Mail(app)

# --- Database Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(10), nullable=False) # 'hr' or 'user'

    # Relationships
    posted_jobs = db.relationship('Job', backref='hr', lazy=True)
    applications = db.relationship('Application', backref='applicant', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def _repr_(self):
        return f'<User {self.username} ({self.role})>'

class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    skills_required = db.Column(db.Text, nullable=False)
    experience_required = db.Column(db.String(50), nullable=False)
    openings = db.Column(db.Integer, nullable=False)
    location = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    jd_path = db.Column(db.String(255), nullable=True)

    hr_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    applications = db.relationship('Application', backref='job', lazy=True, cascade="all, delete-orphan")

    def _repr_(self):
        return f'<Job {self.title}>'

class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resume_path = db.Column(db.String(255), nullable=False)
    match_score = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(20), default='applied') # 'applied', 'shortlisted', 'rejected'
    applied_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)

    def _repr_(self):
        return f'<Application {self.id} for Job {self.job_id} by User {self.user_id}>'

# --- Document Parsing Utility Functions ---
def extract_text_from_pdf(file_path):
    try:
        with pdfplumber.open(file_path) as pdf:
            text = ""
            for page in pdf.pages:
                text += page.extract_text() or ""
        return text
    except Exception as e:
        print(f"Error extracting text from PDF {file_path}: {e}")
        return ""

def extract_text_from_docx(file_path):
    try:
        doc = Document(file_path)
        text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
        return text
    except Exception as e:
        print(f"Error extracting text from DOCX {file_path}: {e}")
        return ""

def parse_document(file_path):
    if not os.path.exists(file_path):
        return ""
    ext = file_path.rsplit('.', 1)[1].lower()
    if ext == 'pdf':
        return extract_text_from_pdf(file_path)
    elif ext in ['docx', 'doc']:
        return extract_text_from_docx(file_path)
    return ""

# --- Resume Matching Logic ---
def calculate_match_score(resume_text, jd_skills):
    # This is a basic keyword matching. For production, consider more advanced NLP.
    if not jd_skills:
        return 0.0

    resume_text_lower = resume_text.lower()
    jd_skills_list = [skill.strip().lower() for skill in jd_skills.split(',') if skill.strip()]
    
    matched_skills_count = 0
    for skill in jd_skills_list:
        if skill in resume_text_lower:
            matched_skills_count += 1
            
    if not jd_skills_list:
        return 0.0
            
    score = (matched_skills_count / len(jd_skills_list)) * 100
    return round(score, 2) # Round to 2 decimal places

# --- Email Sending Utility ---
def send_notification_email(to_email, subject, body):
    try:
        msg = Message(subject, recipients=[to_email])
        msg.body = body
        mail.send(msg)
        print(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
        return False

# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password) and user.role == role:
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash('Logged in successfully!', 'success')
            if role == 'hr':
                return redirect(url_for('hr_dashboard'))
            else:
                return redirect(url_for('jobs'))
        else:
            flash('Invalid email, password, or role.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        phone = request.form.get('phone')
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        role = request.form['role']

        if password != confirm_password:
            flash('Passwords do not match!', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('Email already registered!', 'danger')
            return redirect(url_for('register'))
        
        if User.query.filter_by(username=username).first():
            flash('Username already taken!', 'danger')
            return redirect(url_for('register'))

        new_user = User(username=username, email=email, phone=phone, role=role)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/hr_dashboard')
def hr_dashboard():
    if 'user_id' not in session or session['role'] != 'hr':
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))

    hr_user = User.query.get(session['user_id'])
    jobs = Job.query.filter_by(hr=hr_user).all()
    
    total_jobs = len(jobs)
    total_applications = 0
    shortlisted_count = 0
    rejected_count = 0

    for job in jobs:
        job_applications = job.applications # SQLAlchemy relationship
        job.applications_count = len(job_applications)
        job.shortlisted_count = sum(1 for app_obj in job_applications if app_obj.status == 'shortlisted')
        
        total_applications += job.applications_count
        shortlisted_count += job.shortlisted_count
        rejected_count += sum(1 for app_obj in job_applications if app_obj.status == 'rejected')

    return render_template('hr_dashboard.html', jobs=jobs, total_jobs=total_jobs, 
                           total_applications=total_applications, shortlisted=shortlisted_count, rejected=rejected_count)

@app.route('/post_job', methods=['POST'])
def post_job():
    if 'user_id' not in session or session['role'] != 'hr':
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))

    title = request.form['title']
    description = request.form['description']
    skills_required = request.form['skills_required']
    experience_required = request.form['experience_required']
    openings = int(request.form['openings'])
    location = request.form['location']
    hr_id = session['user_id']
    
    jd_file = request.files.get('jd_file')
    jd_path = None
    if jd_file and jd_file.filename != '':
        # Use secure_filename for safety
        filename = secure_filename(jd_file.filename)
        # Prepend a unique identifier to prevent overwrites and make file names unique
        unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
        jd_path = os.path.join(app.config['UPLOAD_FOLDER_JDS'], unique_filename)
        jd_file.save(jd_path)
    
    new_job = Job(title=title, description=description, skills_required=skills_required,
                  experience_required=experience_required, openings=openings, location=location,
                  hr_id=hr_id, jd_path=jd_path)
    db.session.add(new_job)
    db.session.commit()

    flash('Job posted successfully!', 'success')
    return redirect(url_for('hr_dashboard'))

@app.route('/view_applications/<int:job_id>')
def view_applications(job_id):
    if 'user_id' not in session or session['role'] != 'hr':
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))

    job = Job.query.get(job_id)
    if not job:
        flash('Job not found.', 'danger')
        return redirect(url_for('hr_dashboard'))
    
    # Check if HR owns this job
    if job.hr_id != session['user_id']:
        flash('You are not authorized to view applications for this job.', 'danger')
        return redirect(url_for('hr_dashboard'))

    # Eager load related user data for applications
    applications = Application.query.filter_by(job_id=job_id).join(User).order_by(Application.match_score.desc()).all()
    
    # Attach user details to application objects for easy access in template
    # (Alternatively, you could query directly for combined data if using complex joins)
    display_applications = []
    for app_obj in applications:
        app_data = {
            'id': app_obj.id,
            'resume_path': app_obj.resume_path,
            'match_score': app_obj.match_score,
            'status': app_obj.status,
            'applied_at': app_obj.applied_at,
            'user_name': app_obj.applicant.username, # Access through relationship
            'user_email': app_obj.applicant.email # Access through relationship
        }
        display_applications.append(app_data)

    return render_template('view_applications.html', job=job, applications=display_applications)

@app.route('/process_shortlisting/<int:job_id>', methods=['POST'])
def process_shortlisting(job_id):
    if 'user_id' not in session or session['role'] != 'hr':
        return jsonify({'status': 'error', 'message': 'Unauthorized access.'}), 403

    job = Job.query.get(job_id)
    if not job:
        return jsonify({'status': 'error', 'message': 'Job not found.'}), 404
    
    if job.hr_id != session['user_id']:
        return jsonify({'status': 'error', 'message': 'You are not authorized to process this job.'}), 403

    applications_for_job = Application.query.filter_by(job_id=job_id).all()

    # Extract JD text from file
    jd_text = ""
    if job.jd_path:
        jd_text = parse_document(job.jd_path)
        if not jd_text:
            return jsonify({'status': 'error', 'message': 'Could not extract text from Job Description file. Cannot process shortlisting.'}), 500

    # Calculate match scores for all applications if not already done
    for app_obj in applications_for_job:
        if app_obj.match_score is None or app_obj.status == 'applied': # Re-calculate or calculate initial if 'applied'
            resume_content = parse_document(app_obj.resume_path)
            score = calculate_match_score(resume_content, job.skills_required)
            app_obj.match_score = score
            db.session.add(app_obj) # Mark for update

    db.session.commit() # Commit match scores before sorting

    # Sort applications by match score in descending order
    # Re-query or refresh to ensure sorted list includes newly calculated scores
    applications_for_job = Application.query.filter_by(job_id=job_id).order_by(Application.match_score.desc()).all()

    # Determine shortlist count (e.g., 2x openings)
    shortlist_size = job.openings * 2
    
    shortlisted_count = 0
    rejected_count = 0

    for i, app_obj in enumerate(applications_for_job):
        user = User.query.get(app_obj.user_id)
        if not user:
            print(f"User {app_obj.user_id} not found for application {app_obj.id}. Skipping email.")
            continue 

        if i < shortlist_size:
            # Shortlist
            app_obj.status = 'shortlisted'
            shortlisted_count += 1
            subject = f"Congratulations! You're Shortlisted for {job.title}!"
            body = (f"Dear {user.username},\n\n"
                    f"We are pleased to inform you that you have been shortlisted for the {job.title} position at {job.hr.username}'s company.\n"
                    f"Your match score was {app_obj.match_score:.2f}%.\n\n"
                    f"We will be in touch shortly regarding the next steps in the hiring process.\n\n"
                    f"Best regards,\n"
                    f"The HR Team")
            send_notification_email(user.email, subject, body)
        else:
            # Reject
            app_obj.status = 'rejected'
            rejected_count += 1
            subject = f"Update on Your Application for {job.title}"
            body = (f"Dear {user.username},\n\n"
                    f"Thank you for your interest in the {job.title} position at {job.hr.username}'s company.\n"
                    f"We appreciate you taking the time to apply.\n\n"
                    f"After careful consideration, we regret to inform you that we will not be moving forward with your application at this time.\n\n"
                    f"We wish you the best in your job search.\n\n"
                    f"Sincerely,\n"
                    f"The HR Team")
            send_notification_email(user.email, subject, body)
        
        db.session.add(app_obj) # Mark for update

    db.session.commit() # Commit status changes

    flash(f'Shortlisting processed. {shortlisted_count} shortlisted, {rejected_count} rejected.', 'success')
    return jsonify({'status': 'success', 'message': f'Shortlisting processed. {shortlisted_count} shortlisted, {rejected_count} rejected.'})

@app.route('/jobs')
def jobs():
    if 'user_id' not in session or session['role'] != 'user':
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))

    all_jobs = Job.query.order_by(Job.created_at.desc()).all()
    
    user_applied_job_ids = set()
    if 'user_id' in session:
        user_applications = Application.query.filter_by(user_id=session['user_id']).all()
        user_applied_job_ids = {app.job_id for app in user_applications}

    return render_template('jobs.html', jobs=all_jobs, user_applications=user_applied_job_ids)

@app.route('/apply_job/<int:job_id>', methods=['POST'])
def apply_job(job_id):
    if 'user_id' not in session or session['role'] != 'user':
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))

    job = Job.query.get(job_id)
    if not job:
        flash('Job not found.', 'danger')
        return redirect(url_for('jobs'))

    user_id = session['user_id']
    
    # Check if user already applied
    existing_application = Application.query.filter_by(job_id=job_id, user_id=user_id).first()
    if existing_application:
        flash('You have already applied for this job.', 'warning')
        return redirect(url_for('jobs'))

    resume_file = request.files.get('resume_file')
    if not resume_file or resume_file.filename == '':
        flash('No resume file selected.', 'danger')
        return redirect(url_for('jobs'))

    # Use secure_filename for safety
    filename = secure_filename(resume_file.filename)
    # Create a unique filename to prevent overwrites
    unique_filename = f"{user_id}{job_id}{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
    resume_path = os.path.join(app.config['UPLOAD_FOLDER_RESUMES'], unique_filename)
    resume_file.save(resume_path)

    new_application = Application(job_id=job_id, user_id=user_id, resume_path=resume_path, status='applied')
    db.session.add(new_application)
    db.session.commit()

    flash('Application submitted successfully!', 'success')
    return redirect(url_for('my_applications'))

@app.route('/my_applications')
def my_applications():
    if 'user_id' not in session or session['role'] != 'user':
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))

    # Eager load related job and HR data for applications
    user_applications = Application.query.filter_by(user_id=session['user_id']).join(Job).join(User).order_by(Application.applied_at.desc()).all()
    
    display_applications = []
    for app_obj in user_applications:
        app_data = {
            'id': app_obj.id,
            'job_title': app_obj.job.title,
            'company_name': app_obj.job.hr.username + ' Inc.', # Get company name from HR user who posted the job
            'applied_at': app_obj.applied_at,
            'match_score': app_obj.match_score,
            'status': app_obj.status
        }
        display_applications.append(app_data)

    return render_template('my_applications.html', applications=display_applications)

@app.route('/uploads/resumes/<filename>')
def download_resume(filename):
    # WARNING: Ensure this is secured in production to prevent directory traversal
    return send_from_directory(app.config['UPLOAD_FOLDER_RESUMES'], filename)

@app.route('/uploads/jds/<filename>')
def download_jd(filename):
    # WARNING: Ensure this is secured in production to prevent directory traversal
    return send_from_directory(app.config['UPLOAD_FOLDER_JDS'], filename)


# --- Initial Database Setup and Running the App ---
if _name_ == '_main_':
    with app.app_context():
        db.create_all() # Create database tables based on models

        # Add initial mock data if database is empty
        if not User.query.first():
            hr_user = User(username='HR Manager', email='hr@example.com', phone='123-456-7890', role='hr')
            hr_user.set_password('hrpassword')
            db.session.add(hr_user)

            job_seeker = User(username='John Doe', email='user@example.com', phone='098-765-4321', role='user')
            job_seeker.set_password('userpassword')
            db.session.add(job_seeker)
            db.session.commit() # Commit users first to get their IDs

            # Now use the committed user IDs for jobs
            hr_id = User.query.filter_by(email='hr@example.com').first().id

            job1 = Job(title='Senior Python Developer', description='Looking for an experienced Python developer with strong Django skills.', 
                       skills_required='Python, Django, REST API, PostgreSQL, AWS', experience_required='5+ years', 
                       openings=2, location='Hyderabad', hr_id=hr_id, created_at=datetime.utcnow())
            db.session.add(job1)

            job2 = Job(title='Junior Data Scientist', description='Entry-level position for a data enthusiast.', 
                       skills_required='Python, Machine Learning, Pandas, NumPy, SQL', experience_required='0-2 years', 
                       openings=5, location='Bangalore', hr_id=hr_id, created_at=datetime.utcnow())
            db.session.add(job2)
            db.session.commit()

            print("Initial users and jobs added to the database.")

    app.run(debug=True)