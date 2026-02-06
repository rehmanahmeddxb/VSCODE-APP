import os
import io
import secrets
import json
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, Response, make_response
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date
from sqlalchemy import func, case, text
from types import SimpleNamespace
from models import db, User, Client, Material, Entry, PendingBill, Booking, BookingItem, Payment, Invoice, BillCounter, DirectSale, DirectSaleItem, GRN, GRNItem, Delivery, DeliveryItem, Settings

app = Flask(__name__)
# Increase max content length to 16MB to handle large JSON imports
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Use environment variable for secret key or generate a secure one
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'instance', 'ahmed_cement.db')

if not os.path.exists(os.path.join(basedir, 'instance')):
    os.makedirs(os.path.join(basedir, 'instance'))

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)


def generate_client_code():
    """Generate next client code in format tmpc-000001"""
    last_client = Client.query.filter(Client.code.like('tmpc-%')).order_by(
        Client.code.desc()).first()
    if last_client and last_client.code:
        try:
            num = int(last_client.code.split('-')[1]) + 1
        except:
            num = 1
    else:
        num = 1
    return f"tmpc-{num:06d}"


def generate_material_code():
    """Generate next material code in format tmpm-00001"""
    last_material = Material.query.filter(
        Material.code.like('tmpm-%')).order_by(Material.code.desc()).first()
    if last_material and last_material.code:
        try:
            num = int(last_material.code.split('-')[1]) + 1
        except:
            num = 1
    else:
        num = 1
    return f"tmpm-{num:05d}"


def get_next_bill_no():
    """Reserved for future use. Auto-bill removed as per user request."""
    return ""


def save_photo(file):
    """Save uploaded photo and return filename"""
    if file and file.filename != '':
        filename = secure_filename(
            f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
        upload_folder = os.path.join(basedir, 'static', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        file.save(file_path)
        return filename
    return None


def _ensure_user_password_column():
    """Ensure `password_hash` column exists on `user` table and copy legacy `password` values."""
    try:
        rows = db.session.execute(text("PRAGMA table_info('user')")).fetchall()
        cols = [r[1] for r in rows]
        if 'password_hash' not in cols:
            db.session.execute(text("ALTER TABLE user ADD COLUMN password_hash VARCHAR(200);"))
            if 'password' in cols:
                db.session.execute(text("UPDATE user SET password_hash = password WHERE password_hash IS NULL;"))
            db.session.commit()
    except Exception:
        db.session.rollback()


def _ensure_model_columns():
    """Add any missing columns declared in models but missing in the DB."""
    from sqlalchemy import String, Integer, Float, Date, DateTime, Boolean, Text

    try:
        for table in db.metadata.sorted_tables:
            rows = db.session.execute(text(f"PRAGMA table_info('{table.name}')")).fetchall()
            existing_cols = [r[1] for r in rows]
            for col in table.columns:
                if col.name not in existing_cols:
                    coltype = col.type
                    sqltype = 'VARCHAR(200)'
                    if isinstance(coltype, (String, Text)):
                        sqltype = 'VARCHAR(200)'
                    elif isinstance(coltype, (Integer, Boolean)):
                        sqltype = 'INTEGER'
                    elif isinstance(coltype, Float):
                        sqltype = 'REAL'
                    elif isinstance(coltype, Date):
                        sqltype = 'DATE'
                    elif isinstance(coltype, DateTime):
                        sqltype = 'DATETIME'

                    try:
                        db.session.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {sqltype};"))
                    except Exception:
                        db.session.rollback()
        db.session.commit()
    except Exception:
        db.session.rollback()


with app.app_context():
    db.create_all()
    try:
        _ensure_user_password_column()
    except Exception:
        pass

    try:
        _ensure_model_columns()
    except Exception:
        pass


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ==================== BOOKING ROUTES ====================

@app.route('/bookings')
@login_required
def bookings_page():
    bookings = Booking.query.order_by(Booking.date_posted.desc()).all()
    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()
    materials = Material.query.order_by(Material.name.asc()).all()
    counter = BillCounter.query.first()
    if not counter:
        counter = BillCounter(count=1000)
        db.session.add(counter)
        db.session.commit()
    next_auto = f"#{counter.count}"
    return render_template('bookings.html',
                           bookings=bookings,
                           clients=clients,
                           materials=materials,
                           next_auto=next_auto)


@app.route('/add_booking', methods=['POST'])
@login_required
def add_booking():
    client_name = request.form.get('client_name', '').strip()
    materials_list = request.form.getlist('material_name[]')
    qtys = request.form.getlist('qty[]')
    rates = request.form.getlist('unit_rate[]')
    amount = float(request.form.get('amount', 0) or 0)
    paid_amount = float(request.form.get('paid_amount', 0) or 0)
    manual_bill_no = request.form.get('manual_bill_no', '').strip()

    photo_path = save_photo(request.files.get('photo'))

    # Find client by name or code
    client = Client.query.filter((Client.name == client_name) | (Client.code == client_name)).first()
    
    if not client:
        # Fallback for code searching in case client_name was passed as code
        client = Client.query.filter(Client.code.ilike(f"%{client_name}%")).first()
    
    if not client:
        # Try finding by name (case-insensitive)
        client = Client.query.filter(Client.name.ilike(f"%{client_name}%")).first()

    if not client:
        flash(f'Client "{client_name}" not found. Please add client first.', 'danger')
        return redirect(url_for('bookings_page'))

    # Calculate pending amount (what's still owed)
    pending_amount = max(0.0, amount - paid_amount)

    # Create the booking
    booking = Booking(client_name=client.name,
                      amount=amount,
                      paid_amount=paid_amount,
                      manual_bill_no=manual_bill_no,
                      photo_path=photo_path)
    db.session.add(booking)
    db.session.flush()

    # Add booking items
    for mat, qty, rate in zip(materials_list, qtys, rates):
        if mat:
            db.session.add(
                BookingItem(booking_id=booking.id,
                            material_name=mat,
                            qty=float(qty) if qty else 0,
                            price_at_time=float(rate) if rate else 0))

    # Auto-add to PendingBill if there's an outstanding amount and a manual bill no
    if pending_amount > 0 and manual_bill_no:
        existing_pb = PendingBill.query.filter_by(bill_no=manual_bill_no, client_code=client.code).first()
        if existing_pb:
            existing_pb.amount += pending_amount
            existing_pb.reason = f"Booking: {materials_list[0] if materials_list else ''}"
        else:
            db.session.add(PendingBill(
                client_code=client.code,
                client_name=client.name,
                bill_no=manual_bill_no,
                amount=pending_amount,
                reason=f"Booking: {materials_list[0] if materials_list else ''}",
                is_manual=True,
                created_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
                created_by=current_user.username
            ))

    db.session.commit()
    
    msg = f'Booking added successfully'
    if manual_bill_no:
        msg += f' (Bill: {manual_bill_no})'
    if pending_amount > 0:
        msg += f' — Pending amount: {pending_amount}'
    flash(msg, 'success')
    return redirect(url_for('bookings_page'))


@app.route('/edit_bill/Booking/<int:id>', methods=['POST'])
@login_required
def edit_booking(id):
    booking = Booking.query.get_or_404(id)
    
    old_bill_no = booking.manual_bill_no
    old_client = Client.query.filter_by(name=booking.client_name).first()
    old_client_code = old_client.code if old_client else None
    old_pending_amount = max(0.0, (booking.amount or 0) - (booking.paid_amount or 0))
    
    client_code = request.form.get('client_code', '').strip()
    client_name_input = request.form.get('client_name', '').strip()
    
    # Find client by name or code
    client = Client.query.filter((Client.code == client_code) | (Client.name == client_name_input)).first()
    
    if client:
        booking.client_name = client.name
    
    booking.amount = float(request.form.get('amount', 0) or 0)
    booking.paid_amount = float(request.form.get('paid_amount', 0) or 0)
    booking.manual_bill_no = request.form.get('manual_bill_no', '').strip()

    new_photo = save_photo(request.files.get('photo'))
    if new_photo:
        booking.photo_path = new_photo

    # Update booking items
    BookingItem.query.filter_by(booking_id=id).delete()

    materials_list = request.form.getlist('material_name[]')
    qtys = request.form.getlist('qty[]')
    rates = request.form.getlist('unit_rate[]')

    for mat, qty, rate in zip(materials_list, qtys, rates):
        if mat:
            db.session.add(
                BookingItem(booking_id=booking.id,
                            material_name=mat,
                            qty=float(qty) if qty else 0,
                            price_at_time=float(rate) if rate else 0))

    # Update PendingBill
    new_bill_no = booking.manual_bill_no
    new_pending_amount = max(0.0, booking.amount - booking.paid_amount)
    new_client = Client.query.filter_by(name=booking.client_name).first()
    new_client_code = new_client.code if new_client else None

    # Remove old pending bill if exists
    if old_bill_no and old_client_code:
        old_pb = PendingBill.query.filter_by(bill_no=old_bill_no, client_code=old_client_code).first()
        if old_pb:
            old_pb.amount -= old_pending_amount
            if old_pb.amount <= 0:
                db.session.delete(old_pb)

    # Add/update new pending bill if it has a manual bill no
    if new_pending_amount > 0 and new_client_code and new_bill_no:
        new_pb = PendingBill.query.filter_by(bill_no=new_bill_no, client_code=new_client_code).first()
        if new_pb:
            new_pb.amount += new_pending_amount
            new_pb.client_name = booking.client_name
        else:
            db.session.add(PendingBill(
                client_code=new_client_code,
                client_name=booking.client_name,
                bill_no=new_bill_no,
                amount=new_pending_amount,
                reason=f"Booking: {materials_list[0] if materials_list else ''}",
                is_manual=True,
                created_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
                created_by=current_user.username
            ))

    db.session.commit()
    flash('Booking updated', 'success')
    return redirect(url_for('bookings_page'))


# ==================== PAYMENT ROUTES ====================

@app.route('/payments')
@login_required
def payments_page():
    payments = Payment.query.order_by(Payment.date_posted.desc()).all()
    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()
    counter = BillCounter.query.first()
    if not counter:
        counter = BillCounter(count=1000)
        db.session.add(counter)
        db.session.commit()
    next_auto = f"#{counter.count}"
    return render_template('payments.html',
                           payments=payments,
                           clients=clients,
                           next_auto=next_auto)


@app.route('/add_payment', methods=['POST'])
@login_required
def add_payment():
    client_name = request.form.get('client_name', '').strip()
    amount = float(request.form.get('amount', 0) or 0)
    method = request.form.get('method', '')
    manual_bill_no = request.form.get('manual_bill_no', '').strip()
    photo_path = save_photo(request.files.get('photo'))

    # Find client by name or code
    client = Client.query.filter((Client.name == client_name) | (Client.code == client_name)).first()
    if not client:
        # Fallback for code/name searching
        client = Client.query.filter((Client.code.ilike(f"%{client_name}%")) | (Client.name.ilike(f"%{client_name}%"))).first()
    
    if client:
        client_name = client.name

    payment = Payment(client_name=client_name,
                      amount=amount,
                      method=method,
                      manual_bill_no=manual_bill_no,
                      photo_path=photo_path)
    db.session.add(payment)
    db.session.flush()

    # Apply payment to matching pending bills when possible
    remaining = float(amount)
    applied = []

    if client:
        # Prefer matching by manual_bill_no when provided
        if manual_bill_no:
            pending_q = PendingBill.query.filter_by(bill_no=manual_bill_no, client_code=client.code, is_paid=False).order_by(PendingBill.id.asc()).all()
        else:
            # Otherwise apply to oldest unpaid bills for this client
            pending_q = PendingBill.query.filter_by(client_code=client.code, is_paid=False).order_by(PendingBill.id.asc()).all()

        for pb in pending_q:
            if remaining <= 0:
                break
            if pb.is_paid:
                continue
            if remaining >= (pb.amount or 0):
                remaining -= (pb.amount or 0)
                applied.append((pb.bill_no, f'paid Rs.{pb.amount}'))
                pb.amount = 0
                pb.is_paid = True
            else:
                applied.append((pb.bill_no, f'partial Rs.{remaining:.2f}'))
                pb.amount = (pb.amount or 0) - remaining
                remaining = 0

    db.session.commit()

    msg = 'Payment received successfully'
    if applied:
        details = ', '.join([f"{b}: {s}" for b, s in applied])
        msg += f" — applied to: {details}"
    if remaining > 0 and amount > 0:
        msg += f" — Rs.{remaining:.2f} unapplied (advance)"
    flash(msg, 'success')
    return redirect(url_for('payments_page'))


@app.route('/edit_bill/Payment/<int:id>', methods=['POST'])
@login_required
def edit_payment(id):
    payment = Payment.query.get_or_404(id)
    
    client_code = request.form.get('client_code', '').strip()
    client_name_input = request.form.get('client_name', '').strip()
    
    # Find client by name or code
    client = Client.query.filter((Client.code == client_code) | (Client.name == client_name_input)).first()
    
    if client:
        payment.client_name = client.name
    
    payment.amount = float(request.form.get('amount', 0) or 0)
    payment.method = request.form.get('method', '')
    payment.manual_bill_no = request.form.get('manual_bill_no', '').strip()

    new_photo = save_photo(request.files.get('photo'))
    if new_photo:
        payment.photo_path = new_photo

    db.session.commit()
    flash('Payment updated', 'success')
    return redirect(url_for('payments_page'))


# ==================== DIRECT SALES ROUTES ====================

@app.route('/direct_sales')
@login_required
def direct_sales_page():
    sales = DirectSale.query.order_by(DirectSale.date_posted.desc()).all()
    materials = Material.query.order_by(Material.name.asc()).all()
    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()
    categories = sorted(list({c.category for c in clients if c.category}))
    if 'Cash' not in categories:
        categories.insert(0, 'Cash')
    client_name_prefill = request.args.get('client_name', '').strip()
    counter = BillCounter.query.first()
    if not counter:
        counter = BillCounter(count=1000)
        db.session.add(counter)
        db.session.commit()
    next_auto = f"#{counter.count}"
    return render_template('direct_sales.html',
                           sales=sales,
                           materials=materials,
                           clients=clients,
                           categories=categories,
                           next_auto=next_auto,
                           client_name_prefill=client_name_prefill)


@app.route('/add_direct_sale', methods=['POST'])
@login_required
def add_direct_sale():
    client_name = request.form.get('client_name', '').strip() or request.form.get('client_code', '').strip()
    materials_list = request.form.getlist('product_name[]')
    qtys = request.form.getlist('qty[]')
    rates = request.form.getlist('unit_rate[]')
    amount = float(request.form.get('amount', 0) or 0)
    paid_amount = float(request.form.get('paid_amount', 0) or 0)
    manual_bill_no = request.form.get('manual_bill_no', '').strip()

    photo_path = save_photo(request.files.get('photo'))

    category = request.form.get('category', '').strip()

    # Find client by name or code
    client = Client.query.filter((Client.name == client_name) | (Client.code == client_name)).first()
    if not client:
        # Fallback for code/name searching
        client = Client.query.filter((Client.code.ilike(f"%{client_name}%")) | (Client.name.ilike(f"%{client_name}%"))).first()
    
    if client:
        client_name = client.name
        if not category or category in ['Cash', 'General']:
            category = client.category or 'Credit Customer'

    # Handle Cash category (Manual overrides)
    if category.lower() == 'cash':
        manual_client_name = request.form.get('manual_client_name', '').strip()
        if manual_client_name:
            client_name = manual_client_name
        # Unbilled Cash: Disable manual_bill_no requirement
        # If no manual_bill_no is provided for Cash, it remains UNBILLED
        # Unbilled Cash: Disable manual_bill_no requirement
        # If no manual_bill_no is provided for Cash, it remains UNBILLED

    create_invoice = bool(request.form.get('create_invoice'))
    
    hv = request.form.get('has_bill')
    has_bill = True if hv is None else hv in ['on', '1', 'true', 'True']

    pending_amount = max(0.0, amount - paid_amount)

    # Handle invoice creation
    inv = None
    invoice_no = None
    if create_invoice:
        if manual_bill_no:
            invoice_no = manual_bill_no
            is_manual = True
        else:
            # Invoice without manual bill no
            invoice_no = f"INV-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            is_manual = False

        existing_global = Invoice.query.filter_by(invoice_no=invoice_no).first()
        if existing_global and is_manual:
            if client and existing_global.client_code != client.code:
                flash(f'Invoice number "{invoice_no}" is already used by another client.', 'danger')
                return redirect(url_for('direct_sales_page'))

        inv = Invoice.query.filter_by(invoice_no=invoice_no, client_code=(client.code if client else None)).first()
        balance = max(0.0, amount - paid_amount)
        status = 'PAID' if balance <= 0 else ('PARTIAL' if paid_amount > 0 else 'OPEN')

        if inv:
            inv.client_name = client.name if client else client_name
            inv.total_amount = amount
            inv.balance = balance
            inv.is_cash = bool(request.form.get('track_as_cash'))
            inv.status = status
            inv.date = datetime.now().date()
        else:
            inv = Invoice(client_code=(client.code if client else None),
                          client_name=client.name if client else client_name,
                          invoice_no=invoice_no,
                          is_manual=is_manual,
                          date=datetime.now().date(),
                          total_amount=amount,
                          balance=balance,
                          status=status,
                          is_cash=bool(request.form.get('track_as_cash')),
                          created_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
                          created_by=current_user.username)
            db.session.add(inv)
            db.session.flush()

    sale = DirectSale(client_name=client_name,
                      amount=amount,
                      paid_amount=paid_amount,
                      manual_bill_no=manual_bill_no,
                      photo_path=photo_path,
                      category=category)
    db.session.add(sale)
    db.session.flush()

    # Determine bill number for pending bill
    pending_bill_no = manual_bill_no if manual_bill_no else (invoice_no if create_invoice else None)

    # Auto-add to PendingBill if it has a manual bill no or is a tracked credit sale
    # OR if it's an unregistered cash sale (to avoid orphan entries)
    # UNBILLED cash sales are given a dummy bill number to show up in ledgers
    if (pending_amount > 0 and (manual_bill_no or (create_invoice and invoice_no) or (category and category.lower() != 'cash'))) or (category.lower() == 'cash'):
        client_code = client.code if client else None
        
        # Determine bill number for the pending bill record
        # If no bill exists for a cash sale, use a placeholder
        pb_bill_no = pending_bill_no
        if not pb_bill_no and category.lower() == 'cash':
            pb_bill_no = f"CSH-{sale.id}"
            
        # Search by pb_bill_no if it exists
        existing_pb = PendingBill.query.filter_by(bill_no=pb_bill_no, client_code=client_code).first() if pb_bill_no else None
        if not existing_pb:
            db.session.add(PendingBill(
                client_code=client_code,
                client_name=(client.name if client else client_name),
                bill_no=pb_bill_no,
                amount=pending_amount,
                reason=f"Direct Sale: {materials_list[0] if materials_list else ''}",
                is_cash=(category.lower() == 'cash') if category else False,
                is_manual=bool(manual_bill_no),
                is_paid=(pending_amount <= 0),
                created_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
                created_by=current_user.username
            ))

    if create_invoice and inv:
        sale.invoice_id = inv.id

    items_created = []
    for mat, qty, rate in zip(materials_list, qtys, rates):
        if mat:
            dsi = DirectSaleItem(sale_id=sale.id,
                               product_name=mat,
                               qty=float(qty) if qty else 0,
                               price_at_time=float(rate) if rate else 0)
            db.session.add(dsi)
            items_created.append(dsi)

    # Create dispatching Entry rows
    now = datetime.now()
    for item in items_created:
        ledger_bill_ref = manual_bill_no if manual_bill_no else (inv.invoice_no if (create_invoice and inv) else "UNBILLED-" + str(sale.id))
        
        entry = Entry(date=now.strftime('%Y-%m-%d'),
                      time=now.strftime('%H:%M:%S'),
                      type='OUT',
                      material=item.product_name,
                      client=client_name,
                      client_code=(client.code if client else None),
                      qty=item.qty,
                      bill_no=ledger_bill_ref,
                      nimbus_no='Direct Sale',
                      created_by=current_user.username,
                      client_category=category)
        db.session.add(entry)
        
        # Update Material stock (reduce In Hand)
        mat_obj = Material.query.filter_by(name=item.product_name).first()
        if mat_obj:
            mat_obj.total = (mat_obj.total or 0) - item.qty

    db.session.commit()
    msg = 'Direct sale added successfully'
    if create_invoice and inv:
        msg += f" — Invoice: {inv.invoice_no}"
    flash(msg, 'success')
    return redirect(url_for('direct_sales_page'))


@app.route('/add_sale', methods=['POST'])
@login_required
def add_sale():
    return add_direct_sale()


@app.route('/edit_bill/DirectSale/<int:id>', methods=['POST'])
@login_required
def edit_direct_sale(id):
    sale = DirectSale.query.get_or_404(id)
    
    client_code = request.form.get('client_code', '').strip()
    client_name_input = request.form.get('client_name', '').strip()
    
    # Find client by name or code
    client = Client.query.filter((Client.code == client_code) | (Client.name == client_name_input)).first()
    
    if client:
        sale.client_name = client.name
    
    sale.category = request.form.get('category', '')
    sale.amount = float(request.form.get('amount', 0) or 0)
    sale.paid_amount = float(request.form.get('paid_amount', 0) or 0)
    sale.manual_bill_no = request.form.get('manual_bill_no', '').strip()

    new_photo = save_photo(request.files.get('photo'))
    if new_photo:
        sale.photo_path = new_photo

    DirectSaleItem.query.filter_by(sale_id=id).delete()

    materials_list = request.form.getlist('product_name[]')
    qtys = request.form.getlist('qty[]')
    rates = request.form.getlist('unit_rate[]')

    for mat, qty, rate in zip(materials_list, qtys, rates):
        if mat:
            db.session.add(
                DirectSaleItem(sale_id=sale.id,
                               product_name=mat,
                               qty=float(qty) if qty else 0,
                               price_at_time=float(rate) if rate else 0))

    db.session.commit()
    flash('Direct sale updated', 'success')
    return redirect(url_for('direct_sales_page'))


# ==================== BILL ROUTES ====================

@app.route('/view_bill/<path:bill_no>')
@login_required
def view_bill(bill_no):
    booking = Booking.query.filter(
        (Booking.manual_bill_no == bill_no)
    ).first()
    
    payment = Payment.query.filter(
        (Payment.manual_bill_no == bill_no)
    ).first()
    
    invoice = Invoice.query.filter(
        (Invoice.invoice_no == bill_no)
    ).first()

    if booking:
        return render_template('view_bill.html', bill=booking, type='Booking', items=booking.items)
    if payment:
        return render_template('view_bill.html', bill=payment, type='Payment', items=[])
    if invoice:
        invoice.amount = invoice.total_amount
        invoice.paid_amount = (invoice.total_amount - invoice.balance) if invoice.total_amount and invoice.balance else 0
        invoice.date_posted = datetime.combine(invoice.date, datetime.min.time()) if invoice.date else None

        items = []
        if getattr(invoice, 'direct_sales', None) and invoice.direct_sales:
            ds = invoice.direct_sales[0]
            items = [{'name': it.product_name, 'qty': it.qty} for it in ds.items]
        if not items and getattr(invoice, 'entries', None):
            items = [{'name': e.material, 'qty': e.qty} for e in invoice.entries]
        return render_template('view_bill.html', bill=invoice, type='Invoice', items=items)

    flash('Bill not found', 'danger')
    return redirect(url_for('index'))


@app.route('/download_invoice/<path:bill_no>')
@login_required
def download_invoice(bill_no):
    inv = Invoice.query.filter_by(invoice_no=bill_no).first()
    if not inv:
        flash('Invoice not found', 'danger')
        return redirect(url_for('index'))

    inv.amount = inv.total_amount
    inv.paid_amount = (inv.total_amount - inv.balance) if inv.total_amount and inv.balance else 0
    inv.date_posted = datetime.combine(inv.date, datetime.min.time()) if inv.date else None

    items = []
    if getattr(inv, 'direct_sales', None) and inv.direct_sales:
        ds = inv.direct_sales[0]
        items = [{'name': it.product_name, 'qty': it.qty} for it in ds.items]
    if not items and getattr(inv, 'entries', None):
        items = [{'name': e.material, 'qty': e.qty} for e in inv.entries]

    rendered = render_template('view_bill.html', bill=inv, type='Invoice', items=items)
    response = make_response(rendered)
    response.headers['Content-Disposition'] = f'attachment; filename=invoice-{inv.invoice_no}.html'
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response


@app.route('/delete_bill/<string:type>/<int:id>')
@login_required
def delete_bill(type, id):
    if current_user.role != 'admin':
        flash('Unauthorized', 'danger')
        return redirect(url_for('index'))

    bill = None
    if type == 'Booking':
        bill = Booking.query.get(id)
        if bill:
            # Also remove associated pending bill
            bill_no = bill.manual_bill_no
            client = Client.query.filter_by(name=bill.client_name).first()
            if client and bill_no:
                PendingBill.query.filter_by(bill_no=bill_no, client_code=client.code).delete()
    elif type == 'Payment':
        bill = Payment.query.get(id)
    elif type == 'Delivery':
        from models import GRN
        bill = GRN.query.get(id)
        if bill:
            # Revert stock
            for item in bill.items:
                mat = Material.query.filter_by(name=item.product_name).first()
                if mat:
                    mat.total = (mat.total or 0) - item.qty
            db.session.delete(bill)
            db.session.commit()
            flash('Delivery (GRN) deleted and stock reverted', 'success')
            return redirect(url_for('grn_page'))

    if bill:
        db.session.delete(bill)
        db.session.commit()
        flash(f'{type} deleted successfully', 'success')
    else:
        flash('Bill not found', 'danger')

    if type == 'Booking':
        return redirect(url_for('bookings_page'))
    if type == 'Payment':
        return redirect(url_for('payments_page'))
    if type == 'DirectSale':
        return redirect(url_for('direct_sales_page'))
    return redirect(url_for('index'))


@app.route('/view_bill_detail/<string:type>/<int:id>')
@login_required
def view_bill_detail(type, id):
    bill = None
    items = []
    if type == 'Booking':
        bill = Booking.query.get_or_404(id)
        items = bill.items
    elif type == 'Payment':
        bill = Payment.query.get_or_404(id)
    elif type == 'DirectSale':
        bill = DirectSale.query.get_or_404(id)
        items = bill.items
    else:
        return "Invalid Bill Type", 400
    return render_template('view_bill.html', bill=bill, type=type, items=items)


# ==================== LEDGER ROUTES ====================

@app.route('/ledger')
@login_required
def ledger_page():
    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()
    return render_template('ledger.html', clients=clients)


@app.route('/ledger/<int:client_id>')
@login_required
def financial_ledger(client_id):
    client = Client.query.get_or_404(client_id)
    
    # 1. Fetch Pending Bills
    pending_bills = PendingBill.query.filter_by(client_code=client.code).order_by(PendingBill.id.desc()).all()
    
    # 2. Financial Ledger
    bookings = Booking.query.filter_by(client_name=client.name).all()
    payments = Payment.query.filter_by(client_name=client.name).all()
    direct_sales = DirectSale.query.filter_by(client_name=client.name).all()

    financial_history = []
    
    for b in bookings:
        debit = b.amount or 0
        credit = b.paid_amount or 0
        financial_history.append({
            'date': b.date_posted,
            'description': 'Booking',
            'bill_no': b.manual_bill_no,
            'debit': debit,
            'credit': credit,
            'type': 'Booking',
            'id': b.id
        })
    
    for p in payments:
        credit = p.amount or 0
        financial_history.append({
            'date': p.date_posted,
            'description': f'Payment ({p.method or "Cash"})',
            'bill_no': p.manual_bill_no,
            'debit': 0,
            'credit': credit,
            'type': 'Payment',
            'id': p.id
        })
    
    for s in direct_sales:
        debit = s.amount or 0
        credit = s.paid_amount or 0
        financial_history.append({
            'date': s.date_posted,
            'description': 'Direct Sale',
            'bill_no': s.manual_bill_no,
            'debit': debit,
            'credit': credit,
            'type': 'DirectSale',
            'id': s.id
        })
    
    # Sort by date (oldest first)
    financial_history.sort(key=lambda x: x['date'] or datetime.min)
    
    # Calculate running balance
    running_balance = 0
    for item in financial_history:
        running_balance += (item['debit'] - item['credit'])
        item['balance'] = running_balance
    
    # Reverse for display (newest first)
    financial_history.reverse()

    # 3. Material Ledger
    deliveries = Entry.query.filter(
        (Entry.client_code == client.code) | (Entry.client == client.name),
        Entry.type == 'OUT'
    ).order_by(Entry.date.desc(), Entry.time.desc()).all()

    material_history = []
    seen_material_bills = set()
    
    # Process Deliveries/Entries
    for d in deliveries:
        material_history.append({
            'date': d.date,
            'material': d.material,
            'qty_added': 0,
            'qty_dispatched': d.qty,
            'bill_no': d.bill_no or d.auto_bill_no,
            'nimbus_no': d.nimbus_no,
            'type': 'Dispatch'
        })
        if d.bill_no:
            seen_material_bills.add(d.bill_no)
        if d.auto_bill_no:
            seen_material_bills.add(d.auto_bill_no)

    # Add Bookings to Material Ledger
    bookings = Booking.query.filter_by(client_name=client.name).all()
    for b in bookings:
        for item in b.items:
            material_history.append({
                'date': b.date_posted.strftime('%Y-%m-%d') if b.date_posted else (b.created_at[:10] if b.created_at else ''),
                'material': item.material_name,
                'qty_added': item.qty,
                'qty_dispatched': 0,
                'bill_no': b.manual_bill_no,
                'nimbus_no': 'Booking',
                'type': 'Booking'
            })

    for s in direct_sales:
        bill_ref = s.manual_bill_no or s.auto_bill_no
        if bill_ref not in seen_material_bills:
            for item in s.items:
                material_history.append({
                    'date': s.date_posted.strftime('%Y-%m-%d') if s.date_posted else '',
                    'material': item.product_name,
                    'qty_added': 0,
                    'qty_dispatched': item.qty,
                    'bill_no': bill_ref,
                    'nimbus_no': 'Direct Sale',
                    'type': 'Dispatch'
                })

    # Sort by date (oldest first)
    material_history.sort(key=lambda x: x['date'] or '')

    # Running balance per material
    mat_balances = {}
    for item in material_history:
        mat = item['material']
        if mat not in mat_balances: mat_balances[mat] = 0
        mat_balances[mat] += (item.get('qty_added', 0) - item.get('qty_dispatched', 0))
        item['balance'] = mat_balances[mat]

    material_history.reverse()

    # Calculate totals
    total_debit = sum(item['debit'] for item in financial_history)
    total_credit = sum(item['credit'] for item in financial_history)
    total_balance = total_debit - total_credit

    return render_template('client_ledger.html',
                           client=client,
                           pending_bills=pending_bills,
                           financial_history=financial_history,
                           material_history=material_history,
                           total_debit=total_debit,
                           total_credit=total_credit,
                           total_balance=total_balance)


@app.route('/financial_ledger/<int:client_id>')
@login_required
def financial_ledger_details(client_id):
    return redirect(url_for('financial_ledger', client_id=client_id))


@app.route('/material_ledger/<int:mat_id>')
@login_required
def material_ledger_page(mat_id):
    material = Material.query.get_or_404(mat_id)
    stock_ins = Entry.query.filter_by(material=material.name, type='IN').all()
    stock_outs = Entry.query.filter_by(material=material.name, type='OUT').all()
    sales = DirectSaleItem.query.filter_by(product_name=material.name).all()

    all_transactions = []
    
    for e in stock_ins:
        entry_date = e.date if not isinstance(e.date, str) else datetime.strptime(e.date, '%Y-%m-%d')
        all_transactions.append({
            'date': entry_date,
            'item': e.material,
            'bill_no': e.bill_no or e.auto_bill_no or '',
            'add': e.qty,
            'delivered': 0,
            'description': 'Stock In'
        })
    
    for e in stock_outs:
        entry_date = e.date if not isinstance(e.date, str) else datetime.strptime(e.date, '%Y-%m-%d')
        all_transactions.append({
            'date': entry_date,
            'item': e.material,
            'bill_no': e.bill_no or e.auto_bill_no or '',
            'add': 0,
            'delivered': e.qty,
            'description': f'Dispatch to {e.client or "Unknown"}'
        })

    all_transactions.sort(key=lambda x: x['date'])
    
    history = []
    running_balance = 0
    for t in all_transactions:
        running_balance += (t['add'] - t['delivered'])
        history.append({
            'date': t['date'].strftime('%d-%m-%Y') if hasattr(t['date'], 'strftime') else t['date'],
            'item': t['item'],
            'bill_no': t['bill_no'],
            'add': t['add'],
            'delivered': t['delivered'],
            'balance': running_balance,
            'description': t['description']
        })

    return render_template('material_ledger.html',
                           material=material,
                           history=history)


@app.route('/client_ledger/<int:id>')
@login_required
def client_ledger(id):
    client = db.session.get(Client, id)
    if client:
        page = request.args.get('page', 1, type=int)
        pagination = Entry.query.filter_by(client=client.name).order_by(
            Entry.date.desc()).paginate(page=page, per_page=10)
        summary_query = db.session.query(
            Entry.material,
            func.sum(Entry.qty).label('total')).filter_by(
                client=client.name).group_by(Entry.material).all()
        summary = {row.material: row.total for row in summary_query}
        total_qty = db.session.query(func.sum(Entry.qty)).filter_by(client=client.name).scalar() or 0

        pending_photos = {
            b.bill_no: b.photo_url
            for b in PendingBill.query.filter(PendingBill.photo_url != '').all() if b.bill_no
        }

        return render_template('ledger.html',
                               client=client,
                               entries=pagination.items,
                               pagination=pagination,
                               total_qty=total_qty,
                               summary=summary,
                               pending_photos=pending_photos)
    return redirect(url_for('clients'))


# ==================== INVENTORY ROUTES ====================

@app.route('/receiving')
@login_required
def receiving():
    mats = Material.query.order_by(Material.name.asc()).all()
    today = date.today().strftime('%Y-%m-%d')
    return render_template('receiving.html', materials=mats, today_date=today)


@app.route('/dispatching')
@login_required
def dispatching():
    mats = Material.query.order_by(Material.name.asc()).all()
    cls = Client.query.filter(Client.is_active == True).order_by(Client.name.asc()).all()
    today = date.today().strftime('%Y-%m-%d')
    return render_template('dispatching.html',
                           materials=mats,
                           clients=cls,
                           today_date=today)


@app.route('/api/client_booking_status/<client_code>')
@login_required
def api_client_booking_status(client_code):
    from models import Booking, BookingItem
    bookings = Booking.query.filter_by(client_code=client_code).all()
    booking_ids = [b.id for b in bookings]
    items = BookingItem.query.filter(BookingItem.booking_id.in_(booking_ids)).all()
    
    status_data = []
    for item in items:
        status_data.append({
            'material': item.product_name,
            'booked': item.qty,
            'delivered': item.delivered_qty or 0,
            'balance': item.qty - (item.delivered_qty or 0)
        })
    return jsonify(status_data)

@app.route('/add_record', methods=['POST'])
@login_required
def add_record():
    entry_date = request.form.get('date') or datetime.now().strftime('%Y-%m-%d')
    
    if current_user.role == 'user' and entry_date != datetime.now().strftime('%Y-%m-%d'):
        flash('Permission Denied: Standard users cannot add back-dated records.', 'danger')
        return redirect(url_for('index'))

    now = datetime.now()
    client_name = request.form.get('client', '').strip()
    client_code = None
    client_obj = None
    
    if client_name:
        client_obj = Client.query.filter_by(name=client_name).first()
        if not client_obj:
            client_obj = Client.query.filter_by(code=client_name).first()
        if client_obj:
            client_code = client_obj.code
            client_name = client_obj.name

    entry_type = request.form.get('type', 'IN')

    # For OUT dispatches to unknown clients, redirect to Direct Sale
    if entry_type == 'OUT' and not client_obj:
        flash('Unknown client: For cash customers, please use the Direct Sale form.', 'warning')
        return redirect(url_for('direct_sales_page', client_name=client_name or ''))

    entry = Entry(date=entry_date,
                  time=now.strftime('%H:%M:%S'),
                  type=entry_type,
                  material=request.form.get('material', ''),
                  client=client_name,
                  client_code=client_code,
                  qty=float(request.form.get('qty', 0) or 0),
                  bill_no=request.form.get('bill_no', '').strip(),
                  nimbus_no=request.form.get('nimbus_no', '').strip(),
                  created_by=current_user.username)
    db.session.add(entry)
    db.session.flush()

    hv = request.form.get('has_bill')
    has_bill = True if hv is None else hv in ['on', '1', 'true', 'True']

    material_obj = Material.query.filter_by(name=entry.material).first()
    unit_price = (material_obj.unit_price if material_obj else 0) or 0
    amount = float(entry.qty) * float(unit_price)

    create_invoice = bool(request.form.get('create_invoice'))

    if client_obj and getattr(client_obj, 'require_manual_invoice', False) and entry_type == 'OUT' and not entry.bill_no and not create_invoice:
        db.session.rollback()
        flash('Manual invoice required for this client.', 'danger')
        return redirect(url_for('dispatching'))

    invoice_no = None
    inv = None
    
    if has_bill and (create_invoice or entry.bill_no):
        if entry.bill_no:
            invoice_no = entry.bill_no
            is_manual = True
        else:
            invoice_no = get_next_bill_no()
            entry.auto_bill_no = invoice_no
            is_manual = False

        existing_global = Invoice.query.filter_by(invoice_no=invoice_no).first()
        if existing_global and not is_manual:
            while Invoice.query.filter_by(invoice_no=invoice_no).first():
                invoice_no = get_next_bill_no()
            entry.auto_bill_no = invoice_no
        elif existing_global and is_manual:
            if existing_global.client_code != entry.client_code:
                db.session.rollback()
                flash(f'Invoice number "{invoice_no}" is already used by another client.', 'danger')
                return redirect(url_for('dispatching'))

        inv = Invoice.query.filter_by(invoice_no=invoice_no, client_code=entry.client_code).first()
        if inv:
            inv.client_name = entry.client
            inv.total_amount = amount
            inv.balance = amount
            inv.is_cash = bool(request.form.get('track_as_cash'))
            inv.date = datetime.strptime(entry.date, '%Y-%m-%d').date() if entry.date else datetime.now().date()
        else:
            inv = Invoice(client_code=entry.client_code,
                          client_name=entry.client,
                          invoice_no=invoice_no,
                          is_manual=is_manual,
                          date=datetime.strptime(entry.date, '%Y-%m-%d').date() if entry.date else datetime.now().date(),
                          total_amount=amount,
                          balance=amount,
                          is_cash=bool(request.form.get('track_as_cash')),
                          created_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
                          created_by=current_user.username)
            db.session.add(inv)
            db.session.flush()
        entry.invoice_id = inv.id

    # Pending Bill logic for OUT entries
    if entry_type == 'OUT':
        if has_bill and (entry.bill_no or entry.auto_bill_no):
            bill_no_val = entry.bill_no or entry.auto_bill_no

            existing_pb = PendingBill.query.filter_by(bill_no=bill_no_val, client_code=entry.client_code).first()
            if existing_pb:
                existing_pb.client_name = entry.client
                existing_pb.amount = amount
                existing_pb.reason = f"Dispatch: {entry.material}"
                existing_pb.created_at = datetime.now().strftime('%Y-%m-%d %H:%M')
                existing_pb.created_by = current_user.username
            else:
                db.session.add(PendingBill(
                    client_code=entry.client_code,
                    client_name=entry.client,
                    bill_no=bill_no_val,
                    amount=amount,
                    reason=f"Dispatch: {entry.material}",
                    created_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
                    created_by=current_user.username
                ))
        elif request.form.get('track_as_cash'):
            db.session.add(PendingBill(
                client_code=entry.client_code,
                client_name=entry.client,
                bill_no='',
                amount=amount,
                reason=f"Cash Delivery: {entry.material}",
                is_cash=True,
                created_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
                created_by=current_user.username
            ))

    db.session.commit()
    flash("Record Saved", "success")
    return redirect(url_for('index'))


@app.route('/edit_entry/<int:id>', methods=['POST'])
@login_required
def edit_entry(id):
    e = db.session.get(Entry, id)
    if not e:
        return redirect(url_for('index'))

    today_str = date.today().strftime('%Y-%m-%d')
    if current_user.role != 'admin' and e.date != today_str:
        flash('Permission Denied: Only Admins can edit back-dated records.', 'danger')
        return redirect(url_for('index'))

    old_bill_no = e.bill_no
    old_client_code = e.client_code

    e.date = request.form.get('date') or e.date
    e.time = request.form.get('time') or e.time
    e.type = request.form.get('type') or e.type
    e.material = request.form.get('material') or e.material
    
    client_input = request.form.get('client', '').strip()
    if client_input:
        client_obj = Client.query.filter_by(name=client_input).first()
        if not client_obj:
            client_obj = Client.query.filter_by(code=client_input).first()
        if client_obj:
            e.client = client_obj.name
            e.client_code = client_obj.code
        else:
            e.client = client_input
            e.client_code = None
    else:
        e.client = None
        e.client_code = None
    
    e.qty = float(request.form.get('qty', e.qty) or e.qty)
    e.bill_no = request.form.get('bill_no', '').strip() or None
    e.nimbus_no = request.form.get('nimbus_no', '').strip() or None

    # Synchronize PendingBill
    if e.type == 'OUT':
        if not e.bill_no and old_bill_no:
            PendingBill.query.filter_by(bill_no=old_bill_no, client_code=old_client_code).delete()
        else:
            pb = None
            if e.bill_no:
                pb = PendingBill.query.filter_by(bill_no=e.bill_no, client_code=e.client_code).first()
            if not pb and old_bill_no:
                pb = PendingBill.query.filter_by(bill_no=old_bill_no, client_code=old_client_code).first()

            material_obj = Material.query.filter_by(name=e.material).first()
            unit_price = (material_obj.unit_price if material_obj else 0) or 0
            amount = float(e.qty) * float(unit_price)

            if pb:
                pb.bill_no = e.bill_no or pb.bill_no
                pb.client_name = e.client
                pb.client_code = e.client_code
                pb.amount = amount
                pb.reason = f"Dispatch: {e.material}"
            elif e.bill_no:
                db.session.add(PendingBill(
                    client_code=e.client_code,
                    client_name=e.client,
                    bill_no=e.bill_no,
                    amount=amount,
                    reason=f"Dispatch: {e.material}",
                    created_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
                    created_by=current_user.username
                ))

            if e.bill_no:
                inv = Invoice.query.filter_by(invoice_no=e.bill_no, client_code=e.client_code).first()
                if not inv:
                    inv = Invoice(client_code=e.client_code,
                                  client_name=e.client,
                                  invoice_no=e.bill_no,
                                  is_manual=True,
                                  date=datetime.strptime(e.date, '%Y-%m-%d').date() if e.date else datetime.now().date(),
                                  total_amount=amount,
                                  balance=amount,
                                  created_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
                                  created_by=current_user.username)
                    db.session.add(inv)
                    db.session.flush()
                e.invoice_id = inv.id
            else:
                e.invoice_id = None

    db.session.commit()
    flash('Entry Updated', 'success')
    
    redirect_to = request.form.get('redirect_to')
    if redirect_to == 'tracking':
        return redirect(url_for('tracking'))
    if redirect_to == 'daily_transactions':
        return redirect(url_for('inventory.daily_transactions', date=e.date))
    return redirect(url_for('index'))


@app.route('/delete_entry/<int:id>')
@login_required
def delete_entry(id):
    e = db.session.get(Entry, id)
    if not e:
        return redirect(url_for('index'))

    today_str = date.today().strftime('%Y-%m-%d')
    if current_user.role != 'admin' and e.date != today_str:
        flash('Permission Denied: Only Admins can delete back-dated records.', 'danger')
        return redirect(url_for('index'))

    if e.type == 'OUT' and e.bill_no:
        PendingBill.query.filter_by(bill_no=e.bill_no, client_code=e.client_code).delete()

    d = e.date
    db.session.delete(e)
    db.session.commit()
    flash('Entry Deleted', 'warning')
    return redirect(url_for('index'))


# ==================== TRACKING ROUTES ====================

@app.route('/tracking')
@login_required
def tracking():
    s = request.args.get('start_date')
    end = request.args.get('end_date')
    cl = request.args.get('client')
    m = request.args.get('material')
    bill_no = request.args.get('bill_no', '').strip()
    category = request.args.get('category', '').strip()
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    type_filter = request.args.get('type', '').strip()
    has_bill_filter = request.args.get('has_bill', '').strip()

    has_filter = bool(s or end or cl or m or search or bill_no or category or type_filter or has_bill_filter in ['0', '1'])

    entries = []
    pagination = None
    summary = {}
    total_qty = 0

    if has_filter:
        query = Entry.query
        if s:
            query = query.filter(Entry.date >= s)
        if end:
            query = query.filter(Entry.date <= end)
        if cl:
            query = query.filter(Entry.client == cl)
        if m:
            query = query.filter(Entry.material == m)
        if bill_no:
            query = query.filter(db.or_(Entry.bill_no.ilike(f'%{bill_no}%'), Entry.auto_bill_no.ilike(f'%{bill_no}%')))
        if category:
            query = query.join(Client, Entry.client_code == Client.code).filter(Client.category == category)
        if type_filter:
            query = query.filter(Entry.type == type_filter)
        if has_bill_filter == '1':
            query = query.filter(db.or_(Entry.bill_no != None, Entry.auto_bill_no != None)).filter(db.or_(Entry.bill_no != '', Entry.auto_bill_no != ''))
        if has_bill_filter == '0':
            query = query.filter(db.and_(
                db.or_(Entry.bill_no == None, Entry.bill_no == ''),
                db.or_(Entry.auto_bill_no == None, Entry.auto_bill_no == '')
            ))
        if search:
            query = query.filter(
                db.or_(Entry.material.ilike(f'%{search}%'),
                       Entry.client.ilike(f'%{search}%'),
                       Entry.client_code.ilike(f'%{search}%'),
                       Entry.bill_no.ilike(f'%{search}%'),
                       Entry.nimbus_no.ilike(f'%{search}%')))

        pagination = query.order_by(Entry.date.desc(), Entry.time.desc()).paginate(page=page, per_page=15, error_out=False)
        entries = pagination.items

        # Summary calculation
        base_query = db.session.query(
            Entry.material,
            func.sum(case((Entry.type == 'IN', Entry.qty), else_=-Entry.qty)).label('net'))

        if category:
            base_query = base_query.join(Client, Entry.client_code == Client.code).filter(Client.category == category)
        if s:
            base_query = base_query.filter(Entry.date >= s)
        if end:
            base_query = base_query.filter(Entry.date <= end)
        if cl:
            base_query = base_query.filter(Entry.client == cl)
        if m:
            base_query = base_query.filter(Entry.material == m)

        summary_query = base_query.group_by(Entry.material).all()
        summary = {row.material: row.net for row in summary_query}
        total_qty = sum(summary.values()) if summary else 0

    today_str = date.today().strftime('%Y-%m-%d')
    pending_photos = {
        b.bill_no: b.photo_url
        for b in PendingBill.query.filter(PendingBill.photo_url != '').all()
        if b.bill_no
    }

    return render_template(
        'tracking.html',
        entries=entries,
        pagination=pagination,
        clients=Client.query.filter(Client.is_active == True).order_by(Client.name.asc()).all(),
        materials=Material.query.order_by(Material.name.asc()).all(),
        start_date=s,
        end_date=end,
        client_filter=cl,
        material_filter=m,
        bill_no_filter=bill_no,
        category_filter=category,
        search_query=search,
        now_date=today_str,
        total_qty=total_qty,
        summary=summary,
        has_filter=has_filter,
        pending_photos=pending_photos,
        type_filter=type_filter,
        has_bill_filter=has_bill_filter)


@app.route('/unpaid_transactions')
@login_required
def unpaid_transactions_page():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    material = request.args.get('material')
    bill_no = request.args.get('bill_no')
    status = request.args.get('status', 'unpaid')

    query = PendingBill.query

    if start_date:
        query = query.filter(PendingBill.created_at >= start_date)
    if end_date:
        query = query.filter(PendingBill.created_at <= end_date)
    if material:
        query = query.filter(PendingBill.reason.ilike(f'%{material}%'))
    if bill_no:
        query = query.filter((PendingBill.bill_no.ilike(f'%{bill_no}%')) | (PendingBill.nimbus_no.ilike(f'%{bill_no}%')))
    
    if status == 'paid':
        query = query.filter(PendingBill.is_paid == True)
    elif status == 'unpaid':
        query = query.filter(PendingBill.is_paid == False)
    
    transactions = query.order_by(PendingBill.id.desc()).all()
    materials = Material.query.all()

    return render_template('unpaid_transactions.html', 
                           transactions=transactions, 
                           materials=materials,
                           filters={
                               'start_date': start_date,
                               'end_date': end_date,
                               'material': material,
                               'bill_no': bill_no,
                               'status': status
                           })


# ==================== MAIN ROUTES ====================

@app.route('/')
@login_required
def index():
    today = date.today().strftime('%B %d, %Y')
    client_count = db.session.query(func.count(Client.id)).scalar() or 0
    stats_query = db.session.query(
        Entry.material,
        func.sum(case((Entry.type == 'IN', Entry.qty), else_=0)).label('total_in'),
        func.sum(case((Entry.type == 'OUT', Entry.qty), else_=0)).label('total_out')
    ).group_by(Entry.material).all()
    
    stats = sorted([{
        'name': row.material,
        'in': int(row.total_in or 0),
        'out': int(row.total_out or 0),
        'stock': int((row.total_in or 0) - (row.total_out or 0))
    } for row in stats_query], key=lambda x: x['name'])
    
    total_stock = sum(s['stock'] for s in stats)
    
    return render_template('index.html',
                           today_date=today,
                           total_stock=int(total_stock),
                           client_count=client_count,
                           stats=stats)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password_hash, str(request.form.get('password'))):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid Credentials', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ==================== CLIENT ROUTES ====================

@app.route('/clients')
@login_required
def clients():
    search = request.args.get('search', '').strip()
    category = request.args.get('category', '').strip()
    page_active = request.args.get('page_active', 1, type=int)
    page_inactive = request.args.get('page_inactive', 1, type=int)

    active_query = Client.query.filter(Client.is_active == True)
    if search:
        active_query = active_query.filter(
            db.or_(Client.name.ilike(f'%{search}%'), Client.code.ilike(f'%{search}%')))
    if category:
        active_query = active_query.filter(Client.category == category)
    active_pagination = active_query.order_by(Client.name.asc()).paginate(page=page_active, per_page=10)

    inactive_query = Client.query.filter(Client.is_active == False)
    if search:
        inactive_query = inactive_query.filter(
            db.or_(Client.name.ilike(f'%{search}%'), Client.code.ilike(f'%{search}%')))
    if category:
        inactive_query = inactive_query.filter(Client.category == category)
    inactive_pagination = inactive_query.order_by(Client.name.asc()).paginate(page=page_inactive, per_page=10)

    all_visible_clients = active_pagination.items + inactive_pagination.items
    for c in all_visible_clients:
        c.total_bills = db.session.query(func.count(PendingBill.id)).filter_by(client_code=c.code).scalar() or 0
        c.total_deliveries = db.session.query(func.sum(Entry.qty)).filter_by(client=c.name, type='OUT').scalar() or 0

    active_clients_list = Client.query.filter(Client.is_active == True).order_by(Client.name.asc()).all()
    
    return render_template('clients.html',
                           active_pagination=active_pagination,
                           inactive_pagination=inactive_pagination,
                           search=search,
                           category=category,
                           active_clients=active_clients_list)


@app.route('/add_client', methods=['POST'])
@login_required
def add_client():
    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip()
    if not name:
        flash('Client name is required', 'danger')
        return redirect(url_for('clients'))
    if not code:
        code = generate_client_code()
    if Client.query.filter_by(code=code).first():
        flash(f'Client code "{code}" already exists', 'danger')
        return redirect(url_for('clients'))
    new_c = Client(name=name,
                   code=code,
                   phone=request.form.get('phone', ''),
                   address=request.form.get('address', ''),
                   category=request.form.get('category', 'General'))
    db.session.add(new_c)
    db.session.commit()
    flash('Client Registered', 'success')
    return redirect(url_for('clients'))


@app.route('/edit_client/<int:id>', methods=['POST'])
@login_required
def edit_client(id):
    c = db.session.get(Client, id)
    if c:
        old_code = c.code
        old_name = c.name
        new_code = request.form.get('code', '').strip()
        new_name = request.form.get('name', '').strip()

        if not new_code:
            flash('Client code is required', 'danger')
            return redirect(url_for('clients'))

        existing = Client.query.filter_by(code=new_code).first()
        if existing and existing.id != id:
            flash(f'Client code "{new_code}" already exists', 'danger')
            return redirect(url_for('clients'))

        if old_code != new_code or old_name != new_name:
            PendingBill.query.filter_by(client_code=old_code).update({
                'client_code': new_code,
                'client_name': new_name
            })
            Entry.query.filter_by(client_code=old_code).update({
                'client_code': new_code,
                'client': new_name
            })
            Entry.query.filter_by(client=old_name).update({'client': new_name})

        c.name = new_name
        c.code = new_code
        c.phone = request.form.get('phone', '')
        c.address = request.form.get('address', '')
        c.category = request.form.get('category', 'General')

        db.session.commit()
        flash('Client updated', 'success')
    return redirect(url_for('clients'))


@app.route('/delete_client/<int:id>')
@login_required
def delete_client(id):
    c = db.session.get(Client, id)
    if c:
        db.session.delete(c)
        db.session.commit()
        flash('Client Deleted', 'warning')
    return redirect(url_for('clients'))


@app.route('/transfer_client/<int:id>', methods=['POST'])
@login_required
def transfer_client(id):
    source_client = db.session.get(Client, id)
    target_client_id = request.form.get('target_client_id')
    if not source_client or not target_client_id:
        flash('Invalid transfer request', 'danger')
        return redirect(url_for('clients'))

    target_client = db.session.get(Client, int(target_client_id))
    if not target_client:
        flash('Target client not found', 'danger')
        return redirect(url_for('clients'))

    if target_client.id == source_client.id:
        flash('Cannot transfer to the same client', 'danger')
        return redirect(url_for('clients'))

    if not target_client.is_active:
        flash('Cannot transfer to an inactive client', 'danger')
        return redirect(url_for('clients'))

    entries_updated = Entry.query.filter_by(client_code=source_client.code).update({
        'client': target_client.name,
        'client_code': target_client.code
    })
    bills_updated = PendingBill.query.filter_by(client_code=source_client.code).update({
        'client_name': target_client.name,
        'client_code': target_client.code
    })

    source_client.is_active = False
    source_client.transferred_to_id = target_client.id
    db.session.commit()

    flash(f'Transferred {entries_updated} entries and {bills_updated} bills.', 'success')
    return redirect(url_for('clients'))


@app.route('/reclaim_client/<int:id>', methods=['POST'])
@login_required
def reclaim_client(id):
    source_client = db.session.get(Client, id)
    if not source_client or source_client.is_active or not source_client.transferred_to_id:
        flash('Invalid reclaim request', 'danger')
        return redirect(url_for('clients', show_inactive=1))

    target_client = db.session.get(Client, source_client.transferred_to_id)
    if not target_client:
        flash('Target client not found', 'danger')
        return redirect(url_for('clients', show_inactive=1))

    source_client.is_active = True

    entries_reclaimed = Entry.query.filter_by(
        client_code=target_client.code, client=target_client.name).update({
            'client': source_client.name,
            'client_code': source_client.code
        })
    bills_reclaimed = PendingBill.query.filter_by(
        client_code=target_client.code, client_name=target_client.name).update({
            'client_name': source_client.name,
            'client_code': source_client.code
        })

    source_client.transferred_to_id = None
    db.session.commit()

    flash(f'Reclaimed {entries_reclaimed} entries and {bills_reclaimed} bills.', 'success')
    return redirect(url_for('clients'))


# ==================== MATERIAL ROUTES ====================

@app.route('/materials')
@login_required
def materials():
    page = request.args.get('page', 1, type=int)
    pagination = Material.query.order_by(Material.name.asc()).paginate(page=page, per_page=10)
    return render_template('materials.html', materials=pagination.items, pagination=pagination)


@app.route('/add_material', methods=['POST'])
@login_required
def add_material():
    name = request.form.get('material_name', '').strip()
    code = request.form.get('material_code', '').strip()
    if not name:
        flash('Material name is required', 'danger')
        return redirect(url_for('materials'))
    if not code:
        code = generate_material_code()
    if Material.query.filter_by(code=code).first():
        flash(f'Material code "{code}" already exists', 'danger')
        return redirect(url_for('materials'))
    db.session.add(Material(name=name, code=code))
    db.session.commit()
    flash('Brand Added', 'success')
    return redirect(url_for('materials'))


@app.route('/edit_material/<int:id>', methods=['POST'])
@login_required
def edit_material(id):
    m = db.session.get(Material, id)
    if m:
        new_code = request.form.get('material_code', '').strip()
        new_name = request.form.get('material_name', '').strip()
        if not new_code:
            flash('Material code is required', 'danger')
            return redirect(url_for('materials'))
        existing = Material.query.filter_by(code=new_code).first()
        if existing and existing.id != id:
            flash(f'Material code "{new_code}" already exists', 'danger')
            return redirect(url_for('materials'))
        old_name = m.name
        for e in Entry.query.filter_by(material=old_name).all():
            e.material = new_name
        m.name = new_name
        m.code = new_code
        db.session.commit()
        flash('Brand Updated', 'info')
    return redirect(url_for('materials'))


@app.route('/delete_material/<int:id>')
@login_required
def delete_material(id):
    m = db.session.get(Material, id)
    if m:
        db.session.delete(m)
        db.session.commit()
        flash('Brand Removed', 'warning')
    return redirect(url_for('materials'))


# ==================== PENDING BILLS ROUTES ====================

@app.route('/pending_bills')
@login_required
def pending_bills():
    page = request.args.get('page', 1, type=int)
    category = request.args.get('category', '').strip()
    filters = {
        'client_code': request.args.get('client_code', '').strip(),
        'bill_no': request.args.get('bill_no', '').strip(),
        'bill_from': request.args.get('bill_from', '').strip(),
        'bill_to': request.args.get('bill_to', '').strip(),
        'category': category,
        'is_cash': request.args.get('is_cash', '').strip()
    }
    
    query = PendingBill.query
    
    if filters['client_code']:
        query = query.filter(PendingBill.client_code == filters['client_code'])
    if filters['bill_no']:
        query = query.filter(PendingBill.bill_no.ilike(f"%{filters['bill_no']}%"))
    if filters['is_cash'] != '':
        query = query.filter(PendingBill.is_cash == (filters['is_cash'] == '1'))

    if category:
        query = query.join(Client, PendingBill.client_code == Client.code).filter(Client.category == category)

    pagination = query.order_by(PendingBill.id.desc()).paginate(page=page, per_page=15)

    active_clients = Client.query.filter(Client.is_active == True).order_by(Client.name.asc()).all()
    materials = Material.query.order_by(Material.name.asc()).all()
    
    return render_template('pending_bills.html',
                           bills=pagination.items,
                           pagination=pagination,
                           filters=filters,
                           clients=active_clients,
                           materials=materials)


@app.route('/add_pending_bill', methods=['POST'])
@login_required
def add_pending_bill():
    client_code = request.form.get('client_code', '').strip()
    client_obj = Client.query.filter_by(code=client_code).first()

    if not client_obj:
        flash('Invalid Client Code.', 'danger')
        return redirect(url_for('pending_bills'))

    bill = PendingBill(client_code=client_code,
                       client_name=client_obj.name,
                       bill_no=request.form.get('bill_no', '').strip(),
                       nimbus_no=request.form.get('nimbus_no', '').strip(),
                       amount=float(request.form.get('amount') or 0),
                       reason=request.form.get('reason', '').strip(),
                       photo_url=request.form.get('photo_url', '').strip(),
                       created_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
                       created_by=current_user.username)
    db.session.add(bill)
    db.session.commit()
    flash('Pending bill added', 'success')
    return redirect(url_for('pending_bills'))


@app.route('/edit_pending_bill/<int:id>', methods=['POST'])
@login_required
def edit_pending_bill(id):
    bill = db.session.get(PendingBill, id)
    if bill:
        old_bill_no = bill.bill_no
        old_client_code = bill.client_code
        
        client_code = request.form.get('client_code', '').strip()
        client_obj = Client.query.filter_by(code=client_code).first()

        if not client_obj:
            flash('Invalid Client Code.', 'danger')
            return redirect(url_for('pending_bills'))

        bill.client_code = client_code
        bill.client_name = client_obj.name
        bill.bill_no = request.form.get('bill_no', '').strip()
        bill.nimbus_no = request.form.get('nimbus_no', '').strip()
        bill.amount = float(request.form.get('amount') or 0)
        bill.reason = request.form.get('reason', '').strip()
        bill.photo_url = request.form.get('photo_url', '').strip()

        update_data = {
            'bill_no': bill.bill_no,
            'client': bill.client_name,
            'client_code': bill.client_code
        }
        Entry.query.filter_by(bill_no=old_bill_no, client_code=old_client_code).update(update_data)

        db.session.commit()
        flash('Bill updated', 'success')
    return redirect(url_for('pending_bills'))


@app.route('/delete_pending_bill/<int:id>')
@login_required
def delete_pending_bill(id):
    bill = db.session.get(PendingBill, id)
    if bill:
        if current_user.role == 'user':
            bill_date = bill.created_at[:10] if bill.created_at else ''
            if bill_date != date.today().strftime('%Y-%m-%d'):
                flash('Standard users cannot delete back-dated bills.', 'danger')
                return redirect(url_for('pending_bills'))
        db.session.delete(bill)
        db.session.commit()
        flash('Bill deleted', 'warning')
    return redirect(url_for('pending_bills'))


@app.route('/toggle_bill_paid/<int:id>', methods=['POST'])
@login_required
def toggle_bill_paid(id):
    bill = db.session.get(PendingBill, id)
    if bill:
        bill.is_paid = not bill.is_paid
        db.session.commit()
        return jsonify({'success': True, 'is_paid': bill.is_paid})
    return jsonify({'success': False}), 404


@app.route('/export_pending_bills')
@login_required
def export_pending_bills():
    import pandas as pd
    fmt = request.args.get('format', 'excel')
    bills = PendingBill.query.all()
    data = [{
        'ClientCode': b.client_code,
        'BillNo': b.bill_no,
        'ClientName': b.client_name,
        'Amount': b.amount,
        'Reason': b.reason,
        'NimbusNo': b.nimbus_no,
        'IsPaid': 'Yes' if b.is_paid else 'No'
    } for b in bills]
    df = pd.DataFrame(data)
    if fmt == 'csv':
        return Response(
            df.to_csv(index=False),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=pending_bills_{date.today()}.csv"})
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"pending_bills_{date.today()}.xlsx")


@app.route('/import_pending_bills', methods=['POST'])
@login_required
def import_pending_bills():
    import pandas as pd
    file = request.files.get('file')
    if not file or not file.filename:
        flash('No file selected', 'danger')
        return redirect(url_for('pending_bills'))

    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file, low_memory=False)
        else:
            df = pd.read_excel(file)

        count = 0
        for _, row in df.iterrows():
            bill_no = str(row.get('BillNo', '')).strip() if pd.notna(row.get('BillNo')) else ''
            code = str(row.get('ClientCode', '')).strip() if pd.notna(row.get('ClientCode')) else ''
            name = str(row.get('ClientName', '')).strip() if pd.notna(row.get('ClientName')) else ''

            if not bill_no or bill_no == 'nan':
                continue

            if not name or name == 'nan':
                name = "Unknown"

            try:
                amount_str = str(row.get('Amount', '0')).replace(',', '').strip()
                amount = float(amount_str) if amount_str and amount_str != 'nan' else 0
            except:
                amount = 0

            reason = str(row.get('Reason', '')).strip() if pd.notna(row.get('Reason')) else ''
            nimbus_no = str(row.get('NimbusNo', '')).strip() if pd.notna(row.get('NimbusNo')) else ''

            client = None
            if code and code != 'NA':
                client = Client.query.filter_by(code=code).first()
            if not client and name and name != 'Unknown':
                client = Client.query.filter_by(name=name).first()
            if not client:
                new_code = code if code and code != 'NA' else generate_client_code()
                client = Client(code=new_code, name=name, is_active=True)
                db.session.add(client)
                db.session.flush()

            bill = PendingBill(
                client_code=client.code,
                client_name=client.name,
                bill_no=bill_no,
                amount=amount,
                reason=reason,
                nimbus_no=nimbus_no,
                created_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
                created_by=current_user.username)
            db.session.add(bill)
            count += 1

        db.session.commit()
        flash(f'Successfully imported {count} pending bills.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Import failed: {str(e)}', 'danger')

    return redirect(url_for('pending_bills'))


@app.route('/confirm_import', methods=['POST'])
@login_required
def confirm_import():
    try:
        data = request.form.get('import_data')
        if not data:
            flash('No data to import', 'warning')
            return redirect(url_for('pending_bills'))

        imported_list = json.loads(data)
        count = 0
        for item in imported_list:
            client = None
            code = item.get('client_code', '').strip()
            name = item.get('client_name', '').strip()

            if code and code != 'NA':
                client = Client.query.filter_by(code=code).first()
            if not client and name:
                client = Client.query.filter_by(name=name).first()
            if not client:
                new_code = code if code and code != 'NA' else generate_client_code()
                client = Client(code=new_code, name=name, is_active=True)
                db.session.add(client)
                db.session.flush()

            bill = PendingBill(
                client_code=client.code,
                client_name=client.name,
                bill_no=item.get('bill_no'),
                amount=item.get('amount', 0),
                reason=item.get('reason', ''),
                nimbus_no=item.get('nimbus_no', ''),
                created_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
                created_by=current_user.username)
            db.session.add(bill)
            count += 1

        db.session.commit()
        flash(f'Successfully imported {count} pending bills.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Confirmation failed: {str(e)}', 'danger')

    return redirect(url_for('pending_bills'))


# ==================== API ROUTES ====================

@app.route('/api/clients/search')
@login_required
def api_clients_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    clients = Client.query.filter(
        db.or_(Client.name.ilike(f'%{q}%'), Client.code.ilike(f'%{q}%'))).limit(10).all()
    return jsonify([{'name': c.name, 'code': c.code, 'category': c.category} for c in clients])


@app.route('/api/check_bill/<path:bill_no>')
@login_required
def check_bill_api(bill_no):
    entry = Entry.query.filter_by(bill_no=bill_no).first()
    if entry:
        return jsonify({
            'exists': True,
            'url': url_for('tracking', search=bill_no),
            'material': entry.material,
            'qty': int(entry.qty)
        })
    return jsonify({'exists': False})


# ==================== SETTINGS ROUTES ====================

@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html', users=User.query.all())


@app.route('/add_user', methods=['POST'])
@login_required
def add_user():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    un = request.form.get('username', '').strip()
    pw = generate_password_hash(str(request.form.get('password')))
    rl = request.form.get('role', 'user')

    if User.query.filter_by(username=un).first():
        flash('Username exists', 'danger')
    else:
        new_u = User(username=un,
                     password_hash=pw,
                     role=rl,
                     can_view_stock='can_view_stock' in request.form,
                     can_view_daily='can_view_daily' in request.form,
                     can_view_history='can_view_history' in request.form,
                     can_import_export='can_import_export' in request.form,
                     can_manage_directory='can_manage_directory' in request.form)
        db.session.add(new_u)
        db.session.commit()
        flash('User Created', 'success')
    return redirect(url_for('settings'))


@app.route('/edit_user_permissions/<int:id>', methods=['POST'])
@login_required
def edit_user_permissions(id):
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    u = db.session.get(User, id)
    if u and u.username != 'admin':
        u.role = request.form.get('role', 'user')
        u.can_view_stock = 'can_view_stock' in request.form
        u.can_view_daily = 'can_view_daily' in request.form
        u.can_view_history = 'can_view_history' in request.form
        u.can_import_export = 'can_import_export' in request.form
        u.can_manage_directory = 'can_manage_directory' in request.form
        u.restrict_backdated_edit = (request.form.get('role') == 'user')
        db.session.commit()
        flash('Permissions Updated', 'success')
    return redirect(url_for('settings'))


@app.route('/delete_user/<int:id>')
@login_required
def delete_user(id):
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    u = db.session.get(User, id)
    if u and u.username != 'admin':
        db.session.delete(u)
        db.session.commit()
        flash('User Removed', 'warning')
    return redirect(url_for('settings'))


@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    current_user.password_hash = generate_password_hash(str(request.form.get('password')))
    db.session.commit()
    flash('Password Updated', 'success')
    return redirect(url_for('settings'))


@app.route('/delete_selected_data', methods=['POST'])
@login_required
def delete_selected_data():
    if current_user.role != 'admin':
        return redirect(url_for('index'))

    if request.form.get('confirm_text') != "DELETE SELECTED":
        flash('Incorrect confirmation text', 'danger')
        return redirect(url_for('settings'))

    targets = request.form.getlist('delete_targets')
    if not targets:
        flash('No datasets selected for deletion', 'warning')
        return redirect(url_for('settings'))

    try:
        deleted_info = []
        if 'clients' in targets:
            Client.query.delete()
            deleted_info.append('Clients')
        if 'pending_bills' in targets:
            PendingBill.query.delete()
            deleted_info.append('Pending Bills')
        if 'dispatching' in targets:
            Entry.query.filter_by(type='OUT').delete()
            deleted_info.append('Dispatching Entries')
        if 'receiving' in targets:
            Entry.query.filter_by(type='IN').delete()
            deleted_info.append('Receiving Entries')
        if 'materials' in targets:
            Material.query.delete()
            deleted_info.append('Materials')
        if 'direct_sales' in targets:
            DirectSaleItem.query.delete()
            DirectSale.query.delete()
            deleted_info.append('Direct Sales')
        if 'payments' in targets:
            Payment.query.delete()
            deleted_info.append('Payments')
        if 'bookings' in targets:
            BookingItem.query.delete()
            Booking.query.delete()
            deleted_info.append('Bookings')

        db.session.commit()
        flash(f'Data Wiped: {", ".join(deleted_info)}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Wipe failed: {str(e)}', 'danger')

    return redirect(url_for('settings'))


@app.route('/delete_all_data', methods=['POST'])
@login_required
def delete_all_data():
    return redirect(url_for('settings'))


@app.route('/import_jumble')
@login_required
def import_jumble_view():
    return render_template('import_jumble.html')


# ==================== GRN ROUTES ====================

@app.route('/grn', methods=['GET', 'POST'])
@login_required
def grn():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            supplier = request.form.get('supplier', '').strip()
            manual_bill = request.form.get('manual_bill_no', '').strip()
            auto_bill = get_next_bill_no()
            photo = save_photo(request.files.get('photo'))
            
            new_grn = GRN(supplier=supplier, manual_bill_no=manual_bill, 
                         auto_bill_no=auto_bill, photo_path=photo)
            db.session.add(new_grn)
            db.session.flush()
            
            mat_names = request.form.getlist('mat_name[]')
            qtys = request.form.getlist('qty[]')
            prices = request.form.getlist('price[]')
            
            for name, qty, price in zip(mat_names, qtys, prices):
                if name and qty:
                    qty_val = float(qty)
                    price_val = float(price) if price else 0
                    item = GRNItem(grn_id=new_grn.id, mat_name=name, qty=qty_val, price_at_time=price_val)
                    db.session.add(item)
                    
                    mat = Material.query.filter_by(name=name).first()
                    if mat:
                        mat.total += qty_val
                    
                    entry = Entry(
                        date=datetime.now().strftime('%Y-%m-%d'),
                        time=datetime.now().strftime('%H:%M:%S'),
                        type='IN',
                        material=name,
                        client=supplier,
                        qty=qty_val,
                        bill_no=manual_bill or '',
                        auto_bill_no=auto_bill,
                        created_by=current_user.username
                    )
                    db.session.add(entry)
            
            db.session.commit()
            flash('GRN added successfully!', 'success')
            
        elif action == 'delete':
            grn_id = request.form.get('id')
            grn_obj = GRN.query.get(grn_id)
            if grn_obj:
                for item in grn_obj.items:
                    mat = Material.query.filter_by(name=item.mat_name).first()
                    if mat:
                        mat.total -= item.qty
                db.session.delete(grn_obj)
                db.session.commit()
                flash('GRN deleted successfully!', 'success')
        
        return redirect(url_for('grn'))
    
    grns = GRN.query.order_by(GRN.date_posted.desc()).all()
    materials = Material.query.order_by(Material.name.asc()).all()
    return render_template('grn.html', grns=grns, materials=materials)


# ==================== DELIVERIES ROUTES ====================

@app.route('/deliveries', methods=['GET', 'POST'])
@login_required
def deliveries():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            client_name = request.form.get('client_name', '').strip()
            manual_bill = request.form.get('manual_bill_no', '').strip()
            auto_bill = get_next_bill_no()
            photo = save_photo(request.files.get('photo'))
            
            new_delivery = Delivery(client_name=client_name, manual_bill_no=manual_bill,
                                   auto_bill_no=auto_bill, photo_path=photo)
            db.session.add(new_delivery)
            db.session.flush()
            
            products = request.form.getlist('product[]')
            qtys = request.form.getlist('qty[]')
            
            for product, qty in zip(products, qtys):
                if product and qty:
                    qty_val = float(qty)
                    item = DeliveryItem(delivery_id=new_delivery.id, product=product, qty=qty_val)
                    db.session.add(item)
                    
                    mat = Material.query.filter_by(name=product).first()
                    if mat:
                        mat.total -= qty_val
                    
                    client = Client.query.filter_by(name=client_name).first()
                    client_code = client.code if client else ''
                    
                    entry = Entry(
                        date=datetime.now().strftime('%Y-%m-%d'),
                        time=datetime.now().strftime('%H:%M:%S'),
                        type='OUT',
                        material=product,
                        client=client_name,
                        client_code=client_code,
                        qty=qty_val,
                        bill_no=manual_bill or '',
                        auto_bill_no=auto_bill,
                        created_by=current_user.username
                    )
                    db.session.add(entry)
            
            db.session.commit()
            flash('Delivery added successfully!', 'success')
            
        elif action == 'delete':
            delivery_id = request.form.get('id')
            delivery = Delivery.query.get(delivery_id)
            if delivery:
                for item in delivery.items:
                    mat = Material.query.filter_by(name=item.product).first()
                    if mat:
                        mat.total += item.qty
                db.session.delete(delivery)
                db.session.commit()
                flash('Delivery deleted successfully!', 'success')
        
        return redirect(url_for('deliveries'))
    
    all_deliveries = Delivery.query.order_by(Delivery.date_posted.desc()).all()
    materials = Material.query.order_by(Material.name.asc()).all()
    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()
    return render_template('deliveries.html', deliveries=all_deliveries, materials=materials, clients=clients)


# ==================== BLUEPRINTS ====================

try:
    from blueprints.inventory import inventory_bp
    from blueprints.import_export import import_export_bp
    app.register_blueprint(inventory_bp)
    app.register_blueprint(import_export_bp)
except ImportError:
    pass  # Blueprints not available


# ==================== MAIN ====================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        _ensure_user_password_column()
        _ensure_model_columns()
        
        if not User.query.filter_by(username='admin').first():
            db.session.add(
                User(username='admin',
                     password_hash=generate_password_hash('admin123'),
                     role='admin'))
            
        if not Settings.query.first():
            db.session.add(Settings(currency='PKR', company_name='Ahmed Cement'))
        
        db.session.commit()
    
    app.run(host='0.0.0.0', port=5000, debug=True)