from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, User
from werkzeug.security import generate_password_hash
from flask_login import login_required, current_user, logout_user

profile_bp = Blueprint("profile", __name__)

@profile_bp.route("/profile")
@login_required
def profile_view():
    return render_template("profile.html", user=current_user)

@profile_bp.route("/profile/edit", methods=["GET", "POST"])
@login_required
def profile_edit():
    user = current_user  # or User.query.get(session['user_id'])

    if request.method == "POST":
        new_firstname = request.form.get("firstname")
        new_lastname = request.form.get("lastname")
        new_username = request.form.get("username")
        new_email = request.form.get("email")

        # Check if username is already taken by another user
        existing_user = User.query.filter(User.username == new_username, User.id != user.id).first()
        if existing_user:
            flash("Username already taken. Please choose a different one.", "danger")
            return redirect(url_for("profile.profile_edit"))

        # Optionally, check email as well if it is unique
        existing_email = User.query.filter(User.email == new_email, User.id != user.id).first()
        if existing_email:
            flash("Email already registered. Please use a different email.", "danger")
            return redirect(url_for("profile.profile_edit"))

        # Update user success
        user.firstname = new_firstname
        user.lastname = new_lastname
        user.username = new_username
        user.email = new_email
        db.session.commit()

        flash("Profile updated successfully!", "info")
        return redirect(url_for("profile.profile_view"))

    return render_template("profile_edit.html", user=user)

@profile_bp.route("/profile/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current = request.form.get("current_password")
        new = request.form.get("new_password")
        confirm = request.form.get("confirm_password")

        if not current_user.check_password(current):
            flash("Current password is incorrect", "danger")
            return redirect(url_for("profile.change_password"))

        if new != confirm:
            flash("New passwords do not match", "danger")
            return redirect(url_for("profile.change_password"))

        current_user.password = generate_password_hash(new)
        db.session.commit()

        flash("Password changed successfully!", "info")
        return redirect(url_for("profile.profile_view"))

    return render_template("change_password.html", user=current_user)

@profile_bp.route("/profile/delete", methods=["POST"])
@login_required
def delete_account():
    db.session.delete(current_user)
    db.session.commit()

    logout_user()   # Important!

    flash("Your account has been deleted.", "info")
    return redirect(url_for("login"))

