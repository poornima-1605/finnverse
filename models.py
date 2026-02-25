from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from database import db


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key = True)
    firstname = db.Column(db.String(200), nullable = False )
    lastname = db.Column(db.String(200), nullable = False )
    username = db.Column(db.String(100), unique=True, nullable = False)
    email = db.Column(db.String(150), unique=True, nullable = False)
    password = db.Column(db.String(200), nullable = False )
    notifications = db.relationship('Notification', back_populates='user',cascade='all, delete-orphan',lazy='dynamic')
    budgets = db.relationship('Budget', backref='user', lazy=True)
    reset_token = db.Column(db.String(200), nullable=True)
    token_expiry = db.Column(db.Integer, nullable=True)

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(200))
    expenses = db.relationship('Expense', back_populates='category', lazy=True)
    budgets = db.relationship('Budget', backref='category', lazy=True)


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable = False)
    amount = db.Column(db.Float, nullable = False)
    date = db.Column(db.String(20), nullable = False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    category = db.relationship('Category', back_populates='expenses')
    category_id  = db.Column(db.Integer, db.ForeignKey('category.id'))
    notes = db.Column(db.Text) 
     

class Income(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    notes = db.Column(db.Text)
    user = db.relationship('User', backref='incomes')

    source_id = db.Column(db.Integer, db.ForeignKey('source.id'))
    source = db.relationship('Source', back_populates='incomes') 
    
class Source(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(200))
    incomes = db.relationship('Income', back_populates='source', lazy=True)
    
class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False)    

class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # --- 🆕 New Fields for Budget Tracking ---
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True) # Link to the Category model
    budget_date = db.Column(db.Date, nullable=False)
    # ----------------------------------------
    
    title = db.Column(db.String(140), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False) # Retained existing field
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    seen = db.Column(db.Boolean, default=False)
    
    # Relationships
    user = db.relationship('User', back_populates='notifications')
    category = db.relationship('Category') # New relationship for convenience
class RecurringExpense(db.Model):
    __tablename__ = 'recurring_expense'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)

    title = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category_id = db.Column(db.Integer, nullable=False)

    frequency = db.Column(db.String(10), nullable=False)  
    # monthly / weekly

    next_run_date = db.Column(db.Date, nullable=False)

    notes = db.Column(db.String(255))
    active = db.Column(db.Boolean, default=True)

class PasswordReset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)

    user = db.relationship('User', backref='password_resets')


    









