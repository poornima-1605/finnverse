from flask import Flask, render_template, redirect, url_for, request, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime, timedelta
import secrets
from sqlalchemy import extract 
from dateutil.relativedelta import relativedelta
from flask_migrate import Migrate
import re
import os
from collections import defaultdict
from flask import session, Response, Blueprint
from sqlalchemy import func
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from io import StringIO, BytesIO
from reportlab.lib.pagesizes import A4, letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle 
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas
import matplotlib.pyplot as plt
import matplotlib
from reportlab.lib.utils import ImageReader
from flask import current_app
from fpdf import FPDF
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from sib_api_v3_sdk.rest import ApiException
import requests
from flask_mail import Mail, Message
import sib_api_v3_sdk
from routes_profile import profile_bp 
from database import db
from models import  User, Expense, Source, PasswordReset
from models import Budget , Category , Income, Notification, RecurringExpense


def create_notification_once(user_id, title, message):
    try:
        existing = Notification.query.filter_by(
            user_id=user_id,
            title=title,
            message=message
        ).first()
        if existing:
            return existing

        notif = Notification(user_id=user_id, title=title, message=message)
        db.session.add(notif)
        db.session.commit()
        return notif
    except Exception as e:
        db.session.rollback()
        print("create_notification_once error:", e)
        return None


def get_next_date(start_date, frequency):
    if frequency == "monthly":
        return start_date + relativedelta(months=1)
    elif frequency == "weekly":
        return start_date + timedelta(weeks=1)
    elif frequency == "yearly":
        return start_date + relativedelta(years=1)


def predict_next_month_spending(expenses):
    if len(expenses) < 3:
        return None

    data = []
    for exp in expenses:
        # --- NEW FIX STARTS HERE ---
        # This checks if exp.date is a string; if it is, convert it to a date object
        clean_date = exp.date
        if isinstance(clean_date, str):
            try:
                # Adjust the format '%Y-%m-%d' if your string looks different
                clean_date = datetime.strptime(clean_date, '%Y-%m-%d').date()
            except ValueError:
                continue # Skip this entry if the date format is totally broken
        # --- NEW FIX ENDS HERE ---

        data.append({
            'date': clean_date,
            'amount': exp.amount
        })
    
    df = pd.DataFrame(data)
    
    # Now toordinal() will work because we ensured clean_date is a date object
    df['date_ordinal'] = df['date'].map(lambda x: x.toordinal())
    
    X = df[['date_ordinal']].values
    y = df['amount'].values

    model = LinearRegression()
    model.fit(X, y)

    future_date = datetime.now() + timedelta(days=30)
    future_ordinal = np.array([[future_date.toordinal()]])
    prediction = model.predict(future_ordinal)[0]

    return round(float(prediction), 2)
   
def get_finnbot_advice(total_spent, budget_limit, category_totals):
    """
    Expert System Logic for FinnVerse AI.
    Analyzes current spending and provides actionable financial advice.
    """
    # 1. Handle cases where budget is not set
    if not budget_limit or budget_limit == 0:
        return "👋 Hi! Set a monthly budget limit in your profile so I can monitor your spending health."

    usage_ratio = total_spent / budget_limit

    # 2. Rule-Based Threshold Analysis
    if usage_ratio > 1.0:
        return f"🚨 Budget Exceeded! You are at {int(usage_ratio*100)}% of your limit. Stop non-essential spending immediately."
    
    elif usage_ratio > 0.85:
        return "⚠️ Critical Zone: You've used over 85% of your budget. I suggest postponing any luxury purchases until next month."
    
    elif usage_ratio > 0.60:
        return "🟡 Caution: You've crossed the 60% mark. You're still safe, but watch your daily transactions."

    # 3. Category-Specific Intelligence (The "Smart" part)
    if category_totals:
        # Find the category where the user spent the most
        # Handles cases where 'Uncategorized' might be the top category
        top_category = max(category_totals, key=category_totals.get)
        top_amount = category_totals[top_category]

        # If one category takes up more than 40% of the total spending
        if top_amount > (total_spent * 0.4) and total_spent > 0:
            return f"💡 Analysis: Your '{top_category}' spending is quite high ({int((top_amount/total_spent)*100)}% of total). Try to find cheaper alternatives there!"

    # 4. Default Success State
    return "✅ Great job! Your spending is well-balanced and within your budget goals. Keep it up!"

load_dotenv()


app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", 'default-dev-key')
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    ("DATABASE_URL")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False


db.init_app(app) 
migrate = Migrate(app, db)

app.register_blueprint(profile_bp)



# Brevo SMTP configuration
app.config['MAIL_SERVER'] = 'smtp-relay.brevo.com'
app.config['MAIL_PORT'] = 587  # or 465 for SSL
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False  # True if using port 465
app.config['MAIL_USERNAME'] = '9c12fc001@smtp-brevo.com'
app.config['MAIL_PASSWORD'] = os.getenv("BREVO_SMTP_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = 'help.budgettracker@gmail.com'

mail = Mail(app)


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'



@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


BREVO_API_KEY = os.getenv("BREVO_API_KEY")  
# ... (after load_dotenv())



def send_password_reset_email(to_email, subject, content):
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = BREVO_API_KEY

    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

    email_data = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": to_email}],
        sender={"email": "help.budgettracker@gmail.com", "name": "FinnVerse"},
        subject=subject,
        html_content=content
    )

    try:
        api_instance.send_transac_email(email_data)
        print("Email sent successfully!")
    except ApiException as e:
        print("Error sending email:", e)

def is_strong_password(password):
    return (
        len(password) >= 8 and
        re.search(r'[A-Z]', password) and     # At least one uppercase
        re.search(r'[a-z]', password) and     # At least one lowercase
        re.search(r'\d', password) and        # At least one digit
        re.search(r'[!@#$%^&*(),.?":{}|<>]', password)  # At least one special character
    )





@app.route('/')
def home():
    return render_template('home.html')

@app.route('/about')
def about_page():
    return render_template('about.html')


@app.route('/contact')
def contact_page():
    return render_template('contact.html')



@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        print("Form data:", request.form)

        firstname = request.form.get('firstname')
        lastname = request.form.get('lastname')
        email = request.form.get('email')     # NEW
        username = request.form.get('username')
        raw_password = request.form.get('password')

        # --- PASSWORD STRENGTH CHECK ---
        if not is_strong_password(raw_password):
            flash("Password must be at least 8 characters long and include uppercase, lowercase, digit, and special character.", "danger")
            return render_template("register.html")

        # Hash password
        password = generate_password_hash(raw_password)

        # --- CHECK IF EMAIL ALREADY EXISTS ---
        if User.query.filter_by(email=email).first():
            flash("Email already registered!", "danger")
            return redirect(url_for('register'))

        # --- CHECK IF USERNAME ALREADY EXISTS ---
        if User.query.filter_by(username=username).first():
            flash("Username already exists!", "danger")
            return redirect(url_for('register'))

        # --- CREATE USER ---
        new_user = User(
            firstname=firstname,
            lastname=lastname,
            email=email,          # NEW
            username=username,
            password=password
        )

        db.session.add(new_user)
        db.session.commit()

        flash('Registration successful. Please login!', 'info')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods = ['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username = request.form['username']).first()

        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password!', 'danger')
    return render_template('login.html')


@app.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    curr_month = today.month
    curr_year = today.year

    # --- 1. Recurring Expenses (Keep this as is, it needs to run daily) ---
    recurring_expenses = RecurringExpense.query.filter(
        RecurringExpense.user_id == current_user.id,
        RecurringExpense.active == True,
        RecurringExpense.next_run_date <= today
    ).all()

    for r in recurring_expenses:
        new_expense = Expense(
            title=r.title,
            amount=r.amount,
            date=today,
            user_id=current_user.id,
            category_id=r.category_id,
            notes="Auto recurring expense"
        )
        db.session.add(new_expense)
        r.next_run_date = today + timedelta(days=30 if r.frequency == 'monthly' else 7)
    db.session.commit()

    # --- 2. DATA FETCHING (Now Filtered for Current Month ONLY) ---
    
    # Fetch only this month's expenses for the table
    expenses = Expense.query.filter(
        Expense.user_id == current_user.id,
        extract('month', Expense.date) == curr_month,
        extract('year', Expense.date) == curr_year
    ).all()

    category_totals = {}
    for exp in expenses:
        cat_name = exp.category.name if exp.category else 'Uncategorized'
        category_totals[cat_name] = category_totals.get(cat_name, 0) + exp.amount

    # Monthly Totals for the Top Cards
    total_income = db.session.query(func.sum(Income.amount)).filter(
        Income.user_id == current_user.id,
        extract('month', Income.date) == curr_month,
        extract('year', Income.date) == curr_year
    ).scalar() or 0

    total_expense = db.session.query(func.sum(Expense.amount)).filter(
        Expense.user_id == current_user.id,
        extract('month', Expense.date) == curr_month,
        extract('year', Expense.date) == curr_year
    ).scalar() or 0

    balance = total_income - total_expense

    # --- 3. AI FEATURES (Limited to Current Month Context) ---
    active_budget = Budget.query.filter_by(user_id=current_user.id).first()
    user_budget = active_budget.amount if active_budget else 0

    # Prediction now uses the month-filtered expenses
    ai_prediction = predict_next_month_spending(expenses)
    bot_advice = get_finnbot_advice(total_expense, user_budget, category_totals)
    
    # --- 4. Notifications ---
    notifications = Notification.query.filter_by(user_id=current_user.id, seen=False).all()
    for notif in notifications:
        flash(notif.message, 'danger')
        notif.seen = True  
    db.session.commit()

    return render_template(
        'dashboard.html',
        username=current_user.username,
        expenses=expenses,
        categories=list(category_totals.keys()),
        totals=list(category_totals.values()),
        balance=balance,
        total_income=total_income,
        total_expense=total_expense,
        prediction=ai_prediction,
        bot_advice=bot_advice,
        month_name=today.strftime('%B') # Added to show "February" on UI
    )

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_expense():
    current_date_str = date.today().strftime("%Y-%m-%d")
    categories = Category.query.all()

    if request.method == 'POST':
        title = request.form['title']
        amount = float(request.form['amount'])
        input_date = request.form['date']
        category_id = request.form['category_id']
        notes = request.form.get('notes')  

        # 1. Save new expense
        new_expense = Expense(
            title=title,
            amount=amount,
            date=input_date,
            user_id=current_user.id,
            category_id=category_id,
            notes=notes
        )
        db.session.add(new_expense)
        db.session.commit()

        # 2. RECURRING LOGIC (Now correctly indented inside the POST block)
        if request.form.get('is_recurring'):
            frequency = request.form.get('frequency')
            date_obj = datetime.strptime(input_date, "%Y-%m-%d")

            if frequency == 'monthly':
                next_run = date_obj + timedelta(days=30) # Fixed: Use date_obj
            else:
                next_run = date_obj + timedelta(days=7)

            recurring = RecurringExpense(
                user_id=current_user.id,
                title=title,
                amount=amount,
                category_id=category_id,
                frequency=frequency,
                next_run_date=next_run.date(),
                notes=notes,
                active=True
            )
            db.session.add(recurring)
            db.session.commit()

        # 3. Budget Checking Logic (Now correctly indented)
        budgets = Budget.query.filter_by(
            user_id=current_user.id,
            category_id=category_id
        ).all()

        for b in budgets:
            total_spent = db.session.query(func.sum(Expense.amount)).filter(
                Expense.user_id == current_user.id,
                Expense.category_id == category_id,
                func.date_format(Expense.date, "%Y-%m") == b.date.strftime("%Y-%m")  
            ).scalar() or 0

            remaining = b.amount - total_spent

            if remaining < 0:
                category_name = Category.query.get(category_id).name
                notification_title = "Budget Exceeded"
                
                exists = Notification.query.filter_by(
                    user_id=current_user.id,
                    title=notification_title,
                    category_id=category_id,
                    budget_date=b.date,
                    seen=False
                ).first()

                if not exists:
                    message = f"You exceeded your budget for {category_name} in {b.date.strftime('%B %Y')} by ₹{abs(remaining):.2f}"
                    note = Notification(
                        user_id=current_user.id,
                        title=notification_title,
                        message=message,
                        category_id=category_id, 
                        budget_date=b.date,
                        seen=False
                    )
                    db.session.add(note)
                    db.session.commit()

        # 4. Success Actions (Indented inside POST)
        flash("Expense added successfully!", "success") # Use "success" for the green/teal popup
        return redirect(url_for('dashboard'))

    # This only runs for GET requests
    return render_template('add_expenses.html', categories=categories, today_date=current_date_str)


@app.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_expense(id):
    expense = Expense.query.get_or_404(id)
    categories = Category.query.all()

    if expense.user_id != current_user.id:
        flash('Unauthorized access!', 'error')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        expense.title = request.form['title']
        expense.amount = float(request.form['amount'])
        expense.date = request.form['date']
        expense.category_id = request.form['category_id']
        expense.notes = request.form.get('notes')


        db.session.commit()
        flash('Expense updated!', 'info')
        return redirect(url_for('dashboard'))
    
    return render_template('edit_expenses.html', expense = expense, categories = categories)

@app.route('/expenses')
@login_required
def view_expenses():
    search_query = request.args.get('search', '')
    
    if search_query:
        # Filters expenses by title or category name
        expenses = Expense.query.join(Category).filter(
            Expense.user_id == current_user.id,
            (Expense.title.like(f'%{search_query}%')) | (Category.name.like(f'%{search_query}%'))
        ).all()
    else:
        expenses = Expense.query.filter_by(user_id=current_user.id).all()
    
    return render_template('view_expenses.html', expenses=expenses, search_query=search_query)

@app.route('/expenses/category/<int:category_id>')
@login_required
def filter_expenses_by_category(category_id):
    category = Category.query.get_or_404(category_id)
    expenses = Expense.query.filter_by(user_id=current_user.id, category_id=category_id).all()
    return render_template('view_expenses.html', expenses=expenses, category_filter=category.name)



@app.route('/delete_expense/<int:id>', methods=['POST'])
@login_required
def delete_expense(id):
    expense = Expense.query.get_or_404(id)

    if expense.user_id != current_user.id:
        flash("Unauthorized access!", "danger")
        return redirect(url_for('view_expenses'))

    db.session.delete(expense)
    db.session.commit()
    flash("Expense deleted successfully!", "info")
    return redirect(url_for('view_expenses'))







@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))




@app.route('/budget_overview')
@login_required
def budget_overview():
    # Fetch budgets and expenses for the current user
    budgets = Budget.query.filter_by(user_id=current_user.id).all()
    budget_status = []

    for b in budgets:
        total_spent = db.session.query(func.sum(Expense.amount)).filter(
            Expense.user_id == current_user.id,
            Expense.category_id == b.category_id,
            func.date_format(Expense.date, "%Y-%m") == b.date.strftime("%Y-%m")
        ).scalar() or 0

        remaining = b.amount - total_spent
        category_name = Category.query.get(b.category_id).name

        budget_status.append({
            "category": category_name,
            "budget": b.amount,
            "spent": total_spent,
            "remaining": remaining
        })

    return render_template(
        'overspent_categories.html',  # your HTML file name
        budget_status=budget_status
    )


# Categories CRUD
@app.route('/categories')
@login_required
def view_categories():
    categories = Category.query.all()
    return render_template('view_categories.html', categories=categories)


@app.route('/categories/add', methods=['GET', 'POST'])
@login_required
def add_category():
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        if Category.query.filter_by(name=name).first():
            flash('Category already exists!', 'error')
        else:
            new_cat = Category(name=name, description=description)
            db.session.add(new_cat)
            db.session.commit()
            flash('Category added!', 'info')
            return redirect(url_for('view_categories'))
    return render_template('add_category.html')

@app.route('/categories/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_category(id):
    category = Category.query.get_or_404(id)
    if request.method == 'POST':
        category.name = request.form['name']
        category.description = request.form['description']
        db.session.commit()
        flash('Category updated!', 'info')
        return redirect(url_for('view_categories'))
    return render_template('edit_category.html', category=category)

@app.route('/categories/delete/<int:id>')
@login_required
def delete_category(id):
    category = Category.query.get_or_404(id)
    db.session.delete(category)
    db.session.commit()
    flash('Category deleted!', 'info')
    return redirect(url_for('view_categories'))

@app.route('/add_budget', methods=['GET', 'POST'])
@login_required
def add_budget():
    if request.method == 'POST':
        category_id = request.form['category_id']
        amount = float(request.form['amount'])
        month = request.form['month']

        new_budget = Budget(
            user_id=current_user.id,
            category_id=category_id,
            amount=amount,
            month=month
        )
        db.session.add(new_budget)
        db.session.commit()
        flash('Budget saved successfully!', 'info')
        return redirect(url_for('view_budgets'))

    categories = Category.query.all()
    return render_template('add_budget.html', categories=categories)



@app.route('/edit_budget/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_budget(id):
    budget = Budget.query.get_or_404(id)
    categories = Category.query.all()

    if request.method == 'POST':
        budget.category_id = request.form['category_id']
        budget.amount = request.form['amount']
        budget.date = request.form['date']
        db.session.commit()
        flash("Budget updated successfully.", "info")
        return redirect(url_for('view_budgets'))

    return render_template('edit_budget.html', budget=budget, categories=categories)




@app.route('/view_budgets', methods=['GET', 'POST'])
@login_required
def view_budgets():
    if request.method == 'POST':
        category_id = request.form['category_id']
        amount = float(request.form['amount'])
        month = request.form['month']

        new_budget = Budget(
            user_id=current_user.id,
            category_id=category_id,
            amount=amount,
            month=month
        )
        db.session.add(new_budget)
        db.session.commit()
        flash('Budget saved successfully!', 'info')
        return redirect(url_for('view_budgets'))

    budgets = Budget.query.filter_by(user_id=current_user.id).all()
    categories = Category.query.all()

    return render_template('view_budgets.html', budgets=budgets, categories=categories)

@app.route('/add_income', methods=['GET', 'POST'])
@login_required
def add_income():
    current_date_str = date.today().strftime("%Y-%m-%d")
    sources = Source.query.all()

    
    if request.method == 'POST':
        amount = request.form['amount']
        source_id = int(request.form.get('source_id'))
        input_date = request.form['date']
        notes = request.form.get('notes') 

        

        new_income = Income(
            amount=float(amount),
            source_id= source_id,
            date=input_date,
            user_id=current_user.id,
            notes = notes
        )
        db.session.add(new_income)
        db.session.commit()
        flash('Income added successfully!', 'info')
        return redirect(url_for('dashboard'))  

    return render_template('add_income.html', sources= sources, today_date=current_date_str)

@app.route('/view_incomes')
@login_required
def view_incomes():
    q = request.args.get('search', '').strip()
    
    if q:
        # Join the Source table so we can filter by the source name
        incomes = Income.query.join(Source).filter(
            Income.user_id == current_user.id
        ).filter(
            Source.name.ilike(f'%{q}%') # Use Source.name instead of Income.title
        ).all()
    else:
        incomes = Income.query.filter_by(user_id=current_user.id).all()
    
    return render_template('view_incomes.html', incomes=incomes, search_query=q)


@app.route('/delete_income/<int:income_id>', methods=['POST'])
@login_required
def delete_income(income_id):
    income = Income.query.get_or_404(income_id)

    if income.user_id != current_user.id:
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('view_incomes'))

    db.session.delete(income)
    db.session.commit()
    flash('Income deleted successfully!', 'info')
    return redirect(url_for('view_incomes'))

@app.route('/edit_income/<int:id>', methods=['GET', 'POST'])
def edit_income(id):
    income = Income.query.get_or_404(id)
    sources = Source.query.all()

    if income.user_id != current_user.id:
        flash('Unauthorized access!', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        income.amount = float(request.form['amount'])
        income.date = request.form['date']
        income.notes = request.form.get('notes')
        income.source_id = request.form.get("source_id")

        db.session.commit()
        flash("Income updated successfully!", 'info')
        return redirect(url_for('view_incomes'))

    return render_template('edit_income.html', income=income, sources=sources)

from flask import render_template, session, redirect, url_for, flash
from sqlalchemy import func
from models import db, Income, Expense
from functools import wraps

@app.route("/analysis")
@login_required
def analysis():
    user_id = current_user.id
    today = date.today()
    curr_month = today.month
    curr_year = today.year
    current_month_name = today.strftime("%B")

    # ----- 1. Historical Archive Logic (NEW) -----
    # This finds every unique Month/Year pair the user has data for.
    # We use 'history_list' to create the PDF download table.
    history_list = db.session.query(
        extract('month', Expense.date).label('month'),
        extract('year', Expense.date).label('year')
    ).filter(Expense.user_id == user_id)\
     .group_by('year', 'month')\
     .order_by(extract('year', Expense.date).desc(), extract('month', Expense.date).desc())\
     .all()

    income_source_totals = dict(
        db.session.query(Source.name, func.sum(Income.amount))
        .join(Source, Income.source_id == Source.id)
        .filter(
            Income.user_id == user_id,
            extract('month', Income.date) == curr_month,
            extract('year', Income.date) == curr_year
        )
        .group_by(Source.name)
        .all()
    )
    total_income = sum(income_source_totals.values()) if income_source_totals else 0

    # ----- 2. Expense by Category (FILTERED FOR CURRENT MONTH) -----
    expense_category_totals = dict(
        db.session.query(Category.name, func.sum(Expense.amount))
        .join(Category, Expense.category_id == Category.id)
        .filter(
            Expense.user_id == user_id,
            extract('month', Expense.date) == curr_month,
            extract('year', Expense.date) == curr_year
        )
        .group_by(Category.name)
        .all()
    )
    total_expense = sum(expense_category_totals.values()) if expense_category_totals else 0

    # ----- 4. Monthly Trends (Existing) -----
    income_trends = dict(
        db.session.query(
            func.date_format(Income.date, "%Y-%m"),
            func.sum(Income.amount)
        )
        .filter(Income.user_id == user_id)
        .group_by(func.date_format(Income.date, "%Y-%m"))
        .all()
    )

    expense_trends = dict(
        db.session.query(
            func.date_format(Expense.date, "%Y-%m"),
            func.sum(Expense.amount)
        )
        .filter(Expense.user_id == user_id)
        .group_by(func.date_format(Expense.date, "%Y-%m"))
        .all()
    )

    all_months = sorted(set(income_trends.keys()) | set(expense_trends.keys()))
    monthly_income_data = [float(income_trends.get(m, 0)) for m in all_months]
    monthly_expense_data = [float(expense_trends.get(m, 0)) for m in all_months]

    # ----- 5. Top 3 Summaries (Existing) -----
    top_income_sources = (
        db.session.query(Source.name, func.sum(Income.amount))
        .join(Source, Income.source_id == Source.id)
        .filter(Income.user_id == user_id)
        .group_by(Source.name)
        .order_by(func.sum(Income.amount).desc())
        .limit(3)
        .all()
    )

    top_expense_categories = (
        db.session.query(Category.name, func.sum(Expense.amount))
        .join(Category, Expense.category_id == Category.id)
        .filter(Expense.user_id == user_id)
        .group_by(Category.name)
        .order_by(func.sum(Expense.amount).desc())
        .limit(3)
        .all()
    )

    return render_template(
        "analysis.html",
        income_source_totals=income_source_totals,
        total_income=total_income,
        expense_category_totals=expense_category_totals,
        total_expense=total_expense,
        months=all_months,
        monthly_income_data=monthly_income_data,
        monthly_expense_data=monthly_expense_data,
        top_income_sources=top_income_sources,
        top_expense_categories=top_expense_categories,
        current_month_name=current_month_name,
        history_list=history_list # NEW variable passed to HTML
    )

@app.route('/subscriptions')
@login_required
def subscriptions():
    subs = RecurringExpense.query.filter_by(
        user_id=current_user.id
    ).all()
    return render_template('subscriptions.html', subs=subs)

@app.route('/toggle_subscription/<int:id>')
@login_required
def toggle_subscription(id):
    sub = RecurringExpense.query.get_or_404(id)
    if sub.user_id == current_user.id:
        sub.active = not sub.active  # Flips True to False or vice versa
        db.session.commit()
        status = "Activated" if sub.active else "Paused"
        flash(f"Subscription {status} successfully!", "success")
    return redirect(url_for('subscriptions')) # Replace with your route name

@app.route('/delete_subscription/<int:id>')
@login_required
def delete_subscription(id):
    sub = RecurringExpense.query.get_or_404(id)
    if sub.user_id == current_user.id:
        db.session.delete(sub)
        db.session.commit()
        flash("Subscription deleted!", "danger")
    return redirect(url_for('subscriptions'))

@app.route('/transaction_history', methods=['GET', 'POST'])
@login_required
def transaction_history():
    type_filter = request.args.get('type')
    category_or_source_id = request.args.get('category_or_source')
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    note_search = request.args.get('note_search')

    incomes_query = Income.query.filter_by(user_id=current_user.id)
    expenses_query = Expense.query.filter_by(user_id=current_user.id)

    # Apply filters based on type
    if type_filter == "Income":
        if category_or_source_id:
            incomes_query = incomes_query.filter_by(source_id=int(category_or_source_id))
        expenses_query = None  # Don't fetch expenses
    elif type_filter == "Expense":
        if category_or_source_id:
            expenses_query = expenses_query.filter_by(category_id=int(category_or_source_id))
        incomes_query = None  # Don't fetch incomes
    else:
        if category_or_source_id:
            incomes_query = incomes_query.filter_by(source_id=int(category_or_source_id))
            expenses_query = expenses_query.filter_by(category_id=int(category_or_source_id))

    # Apply date filters
    if from_date:
        if incomes_query:
            incomes_query = incomes_query.filter(Income.date >= from_date)
        if expenses_query:
            expenses_query = expenses_query.filter(Expense.date >= from_date)

    if to_date:
        if incomes_query:
            incomes_query = incomes_query.filter(Income.date <= to_date)
        if expenses_query:
            expenses_query = expenses_query.filter(Expense.date <= to_date)

    # Apply note search filter
    if note_search:
        if incomes_query:
            incomes_query = incomes_query.filter(Income.notes.ilike(f'%{note_search}%'))
        if expenses_query:
            expenses_query = expenses_query.filter(Expense.notes.ilike(f'%{note_search}%'))

    # Final execution
    incomes = incomes_query.order_by(Income.date.desc()).all() if incomes_query else []
    expenses = expenses_query.order_by(Expense.date.desc()).all() if expenses_query else []

    categories = Category.query.all()
    sources = Source.query.all()

    return render_template(
        'transaction_history.html',
        incomes=incomes,
        expenses=expenses,
        categories=categories,
        sources=sources,
        filters={
            'type': type_filter,
            'category_or_source': category_or_source_id,
            'from_date': from_date,
            'to_date': to_date,
            #'note_search': note_search
        }
    )

@app.route('/delete_all_expenses', methods=['POST'])
@login_required
def delete_all_expenses():
    Expense.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    flash("All expenses deleted!", "info")
    return redirect(url_for('view_expenses'))

@app.route('/delete_all_incomes', methods=['POST'])
@login_required
def delete_all_incomes():
    Income.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    flash("All incomes deleted!", "info")
    return redirect(url_for('view_incomes'))

@app.route('/delete_all_budgets', methods=['POST'])
@login_required
def delete_all_budgets():
    Budget.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    flash("All budgets deleted!", "info")
    return redirect(url_for('view_budgets'))

@app.route("/export_analysis_csv")
@login_required
def export_analysis_csv():
    user_id = current_user.id

    # Income Data (Source name instead of source_id)
    income_data = (
        db.session.query(Income.date, Source.name.label("source"), Income.amount, Income.notes)
        .join(Source, Income.source_id == Source.id)
        .filter(Income.user_id == user_id)
        .all()
    )
    income_df = pd.DataFrame(income_data, columns=["Date", "Source", "Amount","Notes"])
    income_df['Date'] = " ' "+ income_df['Date'].astype(str)


    # Expense Data (Category name instead of True/False)
    expense_data = (
        db.session.query(Expense.date, Category.name.label("Category"),Expense.title.label("Title"),Expense.amount, Expense.notes)
        .join(Category, Expense.category_id == Category.id)
        .filter(Expense.user_id == user_id)
        .all()
    )
    expense_df = pd.DataFrame(expense_data, columns=["Date", "Category","Title","Amount", "Notes"])
    expense_df['Date'] = " ' "+ expense_df['Date'].astype(str)

    output = StringIO()
    output.write("Income Records\n")
    income_df.to_csv(output, index=False)
    output.write("\n\nExpense Records\n")
    expense_df.to_csv(output, index=False)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=budget_analysis.csv"}
    )

# Updated route to accept month and year as parameters
@app.route("/export_analysis_pdf/<int:month>/<int:year>")
@login_required
def export_analysis_pdf(month, year):
    reports_dir = os.path.join(current_app.root_path, "static", "reports")
    charts_dir = os.path.join(reports_dir, "charts")
    os.makedirs(charts_dir, exist_ok=True)

    user_id = current_user.id
    
    # Create a name for the month (e.g., "February 2026")
    report_date = date(year, month, 1)
    month_name = report_date.strftime("%B %Y")

    # 1. Fetch Summary Totals (FILTERED BY MONTH/YEAR)
    total_expenses = db.session.query(func.sum(Expense.amount)).filter(
        Expense.user_id == user_id,
        extract('month', Expense.date) == month,
        extract('year', Expense.date) == year
    ).scalar() or 0

    total_income = db.session.query(func.sum(Income.amount)).filter(
        Income.user_id == user_id,
        extract('month', Income.date) == month,
        extract('year', Income.date) == year
    ).scalar() or 0

    net_savings = total_income - total_expenses

    # 2. Fetch Grouped Data (FILTERED BY MONTH/YEAR)
    expense_data = db.session.query(Category.name, func.sum(Expense.amount))\
        .join(Expense).filter(
            Expense.user_id == user_id,
            extract('month', Expense.date) == month,
            extract('year', Expense.date) == year
        ).group_by(Category.name).all()

    income_data = db.session.query(Source.name, func.sum(Income.amount))\
        .join(Income).filter(
            Income.user_id == user_id,
            extract('month', Income.date) == month,
            extract('year', Income.date) == year
        ).group_by(Source.name).all()

    # --- 3. Chart Generation (Same as your logic, just with filtered data) ---
    teal_palette = ['#008080', '#20B2AA', '#40E0D0', '#48D1CC', '#00CED1']
    
    def create_doughnut(data, filename, title):
        if not data: return None
        names = [item[0] for item in data]
        values = [item[1] for item in data]
        plt.figure(figsize=(6, 5))
        plt.pie(values, labels=names, autopct='%1.1f%%', startangle=140, 
                colors=teal_palette, wedgeprops={'width': 0.4, 'edgecolor': 'w'})
        plt.title(title, fontsize=14, pad=20, color='#004d4d', fontweight='bold')
        path = os.path.join(charts_dir, filename)
        plt.savefig(path, bbox_inches='tight')
        plt.close()
        return path

    exp_chart_path = create_doughnut(expense_data, f"exp_{month}_{year}.png", f"Expenses: {month_name}")
    inc_chart_path = create_doughnut(income_data, f"inc_{month}_{year}.png", f"Income: {month_name}")

    # --- 4. Generate Polished PDF ---
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Ensure your font paths are correct
    font_path = os.path.join(current_app.root_path, "static", "fonts")
    pdf.add_font("Noto", "", os.path.join(font_path, "NotoSans-Regular.ttf"), uni=True)
    pdf.add_font("NotoB", "", os.path.join(font_path, "NotoSans-Bold.ttf"), uni=True)
    pdf.add_page()

    # --- Header Banner (Updated to show Month Name) ---
    pdf.set_fill_color(0, 128, 128) 
    pdf.rect(0, 0, 210, 40, 'F')
    pdf.set_y(10)
    pdf.set_font("NotoB", "", 20)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, "FINNVERSE MONTHLY STATEMENT", ln=True, align="C")
    pdf.set_font("Noto", "", 14)
    pdf.cell(0, 10, f"Statement for {month_name}", ln=True, align="C")

    pdf.set_y(42)
    pdf.set_font("Noto", "", 10)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(95, 10, f"Account: {current_user.username}", 0, 0, 'L')
    gen_time = datetime.now().strftime("%d %b %Y, %I:%M %p")
    pdf.cell(95, 10, f"Report Generated: {gen_time}", 0, 1, 'R')

    # --- Executive Summary Box ---
    pdf.set_y(50)
    pdf.set_fill_color(245, 250, 250)
    pdf.rect(10, 50, 190, 30, 'F')
    pdf.set_font("Noto", "", 11)
    pdf.set_text_color(100, 100, 100)
    pdf.set_x(15)
    pdf.cell(63, 10, "Income this Month", 0, 0, 'C')
    pdf.cell(63, 10, "Expenses this Month", 0, 0, 'C')
    pdf.cell(63, 10, "Monthly Balance", 0, 1, 'C')
    
    pdf.set_font("NotoB", "", 16)
    pdf.set_x(15)
    pdf.set_text_color(0, 128, 128)
    pdf.cell(63, 10, f"₹{total_income:,.2f}", 0, 0, 'C')
    pdf.set_text_color(200, 50, 50)
    pdf.cell(63, 10, f"₹{total_expenses:,.2f}", 0, 0, 'C')
    
    # Logic for Balance Color (Green for profit, Red for loss)
    if net_savings >= 0:
        pdf.set_text_color(34, 139, 34)
    else:
        pdf.set_text_color(200, 50, 50)
    pdf.cell(63, 10, f"₹{net_savings:,.2f}", 0, 1, 'C')

    # --- Reusable Table Function ---
    def add_table(header, data, y_pos):
        pdf.set_y(y_pos)
        pdf.set_font("NotoB", "", 14)
        pdf.set_text_color(0, 128, 128)
        pdf.cell(0, 10, header, ln=True)
        pdf.set_fill_color(0, 128, 128)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("NotoB", "", 11)
        pdf.cell(110, 10, " Category/Source", 1, 0, 'L', fill=True)
        pdf.cell(40, 10, " Amount", 1, 1, 'L', fill=True)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Noto", "", 10)
        fill = False
        for name, amt in data:
            pdf.set_fill_color(240, 240, 240) if fill else pdf.set_fill_color(255, 255, 255)
            pdf.cell(110, 8, f" {name}", 1, 0, 'L', fill=True)
            pdf.cell(40, 8, f" ₹{amt:,.2f}", 1, 1, 'L', fill=True)
            fill = not fill

    # Add Expense Table & Doughnut
    if expense_data:
        add_table("Expense Breakdown", expense_data, 90)
        if exp_chart_path:
            pdf.image(exp_chart_path, x=10, y=pdf.get_y() + 5, w=90)
    else:
        pdf.set_y(90)
        pdf.set_font("Noto", "", 10)
        pdf.cell(0, 10, "No expenses recorded for this month.", ln=True)

    # Add Income Table & Doughnut
    pdf.add_page()
    if income_data:
        add_table("Income Sources", income_data, 20)
        if inc_chart_path:
            pdf.image(inc_chart_path, x=10, y=pdf.get_y() + 5, w=90)
    else:
        pdf.set_y(20)
        pdf.set_font("Noto", "", 10)
        pdf.cell(0, 10, "No income recorded for this month.", ln=True)

    final_filename = f"FinnVerse_Report_{month_name.replace(' ', '_')}.pdf"
    pdf_path = os.path.join(reports_dir, final_filename)
    pdf.output(pdf_path)
    return send_file(pdf_path, as_attachment=True)


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()

        if not user:
            flash("No account found with this email!", "danger")
            return redirect(url_for('forgot_password'))

        # Generate reset token
        token = secrets.token_hex(32)

        # Save in database
        reset = PasswordReset(
            user_id=user.id,
            token=token,
            expires_at=datetime.utcnow() + timedelta(minutes=30),
            used=False
        )
        db.session.add(reset)
        db.session.commit()

        # Create reset link
        reset_link = url_for('reset_password', token=token, _external=True)

        # Prepare email
        subject = "Reset Your FinnVerse Password"
        html_content = f"""
        <p>Hi {user.firstname},</p>
        <p>You requested to reset your password. Click the link below to reset it:</p>
        <p><a href="{reset_link}">{reset_link}</a></p>
        <p>This link will expire in 30 minutes.</p>
        <p>If you did not request this, ignore this email.</p>
        """

        # Send email
        send_password_reset_email(email, subject, html_content)

        flash("A password reset link has been sent to your email!", "info")
        return redirect(url_for('login'))

    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    reset_entry = PasswordReset.query.filter_by(token=token, used=False).first()

    if not reset_entry or reset_entry.expires_at < datetime.utcnow():
        flash("Invalid or expired reset link!", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        new_password = request.form.get('password')

        # Update user password
        user = User.query.get(reset_entry.user_id)
        user.password = generate_password_hash(new_password)

        # Mark token as used
        reset_entry.used = True

        db.session.commit()

        flash("Password reset successful! You can now login.", "info")
        return redirect(url_for('login'))

    return render_template('reset_password.html', token=token)

@app.route("/test_db")
def test_db():
    result = db.session.execute("SELECT DATABASE();")
    db_name = result.fetchone()
    return f"Connected to database: {db_name[0]}"



@app.route("/quick_add/<string:template_type>")
@login_required
def quick_add(template_type):
    # Mapping templates to names that should exist in your Category table
    templates = {
        'tea': {'title': 'Chai/Coffee', 'amount': 20, 'cat_name': 'Food'}, 
        'bus': {'title': 'BEST Bus/Auto', 'amount': 15, 'cat_name': 'Transport'},
        'xerox': {'title': 'Printing/Xerox', 'amount': 50, 'cat_name': 'Education'}, 
        'recharge': {'title': 'Mobile Recharge', 'amount': 299, 'cat_name': 'Bills'}, 
        'ott': {'title': 'Netflix/Spotify', 'amount': 199, 'cat_name': 'Entertainment'},
        'gym': {'title': 'Gym/Fitness', 'amount': 1000, 'cat_name': 'Health'}
    }

    if template_type in templates:
        temp = templates[template_type]
        
        # Search for the category ID by name to avoid hardcoding errors
        category = Category.query.filter_by(name=temp['cat_name']).first()
        
        if not category:
            flash(f"Error: Category '{temp['cat_name']}' not found in database!", "danger")
            return redirect(url_for('dashboard'))

        # Create the new expense entry
        new_expense = Expense(
            title=temp['title'],
            amount=temp['amount'],
            category_id=category.id, # Uses the dynamic ID found above
            user_id=current_user.id,
            date=date.today() # Automatically sets to Feb 21, 2026
        )
        
        try:
            db.session.add(new_expense)
            db.session.commit()
            flash(f"✅ Expense {temp['title']} (₹{temp['amount']}) successfully!", "success")
        except Exception as e:
            db.session.rollback()
            flash("Error saving to database.", "danger")
    
    return redirect(url_for('dashboard'))


@app.route("/manage_budgets", methods=["GET", "POST"])
@login_required
def manage_budgets():
    if request.method == "POST":
        target_month_str = request.form.get('month') # Incoming format: "2026-02"
        selected_style = request.form.get('template_style', 'student')
        
        if not target_month_str:
            flash("Please select a month first!", "danger")
            return redirect(url_for('manage_budgets'))

        # 1. Convert "YYYY-MM" string to Year and Month integers
        try:
            year_int, month_int = map(int, target_month_str.split('-'))
            # Create a date object for the 1st of that month
            budget_date = date(year_int, month_int, 1)
        except ValueError:
            flash("Invalid date format.", "danger")
            return redirect(url_for('manage_budgets'))

        # 2. AUTO-SUM INCOME: Find total income for THIS specific month/year
        total_income = db.session.query(func.sum(Income.amount)).filter(
            Income.user_id == current_user.id,
            func.extract('month', Income.date) == month_int,
            func.extract('year', Income.date) == year_int
        ).scalar() or 0

        if total_income <= 0:
            flash(f"No income found for {target_month_str}. Add income before generating a budget!", "warning")
            return redirect(url_for('manage_budgets'))

        # 3. PERSONA TEMPLATES (Weights)
        all_templates = {
            'student': {'Food': 0.25, 'Education': 0.20, 'Transport': 0.15, 'Rent': 0.15, 'Bills': 0.10, 'Entertainment': 0.05, 'Health': 0.03, 'Utilities': 0.03, 'Travel': 0.02, 'Other': 0.02},
            'professional': {'Rent': 0.35, 'Food': 0.15, 'Health': 0.10, 'Transport': 0.10, 'Bills': 0.05, 'Utilities': 0.05, 'Entertainment': 0.05, 'Other': 0.15},
            'saver': {'Rent': 0.30, 'Food': 0.15, 'Bills': 0.10, 'Transport': 0.05, 'Health': 0.05, 'Other': 0.35}
        }

        weights = all_templates.get(selected_style, all_templates['student'])

        # 4. UPSERT LOGIC: Loop through weights and save to DB
        for cat_name, weight in weights.items():
            category = Category.query.filter_by(name=cat_name).first()
            if category:
                calc_amount = round(total_income * weight, 2)
                
                # Check if this user already has a budget for this category and date
                existing = Budget.query.filter_by(
                    user_id=current_user.id, 
                    category_id=category.id, 
                    date=budget_date
                ).first()

                if existing:
                    existing.amount = calc_amount # Update existing
                else:
                    new_b = Budget(
                        user_id=current_user.id,
                        category_id=category.id,
                        amount=calc_amount,
                        date=budget_date
                    )
                    db.session.add(new_b)

        db.session.commit()
        flash(f"Success! Distributed ₹{total_income} using the {selected_style.capitalize()} template.", "success")
        return redirect(url_for('manage_budgets'))

    # GET REQUEST: Fetch all budgets sorted by newest date first
    # This prevents the 'no attribute month' error by fetching the object correctly
    budgets = Budget.query.filter_by(user_id=current_user.id).order_by(Budget.date.desc()).all()
    
    return render_template("manage_budgets.html", budgets=budgets)

@app.route("/delete_budget/<int:id>", methods=["POST"])
@login_required
def delete_budget(id):
    # Search for the budget by ID
    budget_to_delete = Budget.query.get_or_404(id)
    
    # Security Check: Ensure the user only deletes their own data
    if budget_to_delete.user_id != current_user.id:
        flash("Unauthorized access!", "danger")
        return redirect(url_for('manage_budgets'))

    try:
        db.session.delete(budget_to_delete)
        db.session.commit()
        flash("Budget limit removed successfully.", "success")
    except Exception as e:
        db.session.rollback()
        # Log the error for debugging
        print(f"Error: {e}") 
        flash("Could not delete budget record.", "danger")
        
    return redirect(url_for('manage_budgets'))


 
if __name__ == '__main__':
    with app.app_context():
         db.create_all()
    app.run(debug=True) 
