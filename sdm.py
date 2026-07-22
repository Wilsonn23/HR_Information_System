# ===============================================================================================================
# SDM (HUMAN RESOURCES) MODULE
# ===============================================================================================================

from flask import render_template, request, redirect, url_for, flash, session
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, SubmitField
from wtforms.validators import DataRequired, Optional, Length
from werkzeug.security import generate_password_hash

# Import shared resources and models from app.py
from app import app, db, UserEntry

class UserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=50)])
    password = StringField('Password (Isi jika ingin diubah)', validators=[Optional(), Length(min=6)])
    role = SelectField('Role', choices=[('user', 'Staff Operasional'), ('admin', 'Administrator')], validators=[DataRequired()])
    submit = SubmitField('Simpan Pengguna')

@app.route('/users', methods=['GET', 'POST'])
def manage_users():
    if 'logged_user' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    form = UserForm()
    
    if form.validate_on_submit():
        username_clean = form.username.data.strip()
        existing_user = db.session.execute(db.select(UserEntry).where(UserEntry.username == username_clean)).scalar_one_or_none()
        
        if existing_user:
            flash(f"⚠️ Gagal! Username '{username_clean}' sudah digunakan oleh orang lain.", "danger")
        else:
            if not form.password.data:
                flash("⚠️ Password wajib diisi untuk pengguna baru!", "danger")
            else:
                hashed_pw = generate_password_hash(form.password.data)
                new_user = UserEntry(username=username_clean, password=hashed_pw, role=form.role.data)
                db.session.add(new_user)
                db.session.commit()
                flash(f"Pengguna '{username_clean}' berhasil didaftarkan.", "success")
                return redirect(url_for('manage_users'))

    all_users = db.session.execute(db.select(UserEntry).order_by(UserEntry.id)).scalars().all()
    return render_template('sdm/users.html', form=form, users=all_users, active_page='users')

@app.route('/users/delete/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if 'logged_user' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    user_to_delete = db.session.get(UserEntry, user_id)
    
    if user_to_delete and user_to_delete.username == session['logged_user']:
        flash("⚠️ Anda tidak bisa menghapus akun Anda sendiri yang sedang aktif digunakan!", "danger")
    elif user_to_delete:
        username_deleted = user_to_delete.username
        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f"Akun pengguna '{username_deleted}' berhasil dihapus dari sistem.", "success")
    
    return redirect(url_for('manage_users'))
