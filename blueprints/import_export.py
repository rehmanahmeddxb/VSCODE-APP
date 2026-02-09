from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, Response, current_app
from flask_login import login_required, current_user
import pandas as pd
import io
from datetime import datetime, date
from sqlalchemy import func
from models import db, Material, Entry, Client, PendingBill

# Module configuration
MODULE_CONFIG = {
    'name': 'Import/Export Module',
    'description': 'Data import and export functionality',
    'url_prefix': '/import_export',
    'enabled': True
}

import_export_bp = Blueprint('import_export', __name__)

def generate_client_code():
    """Generate next client code in format tmpc-000001"""
    last_client = Client.query.filter(Client.code.like('tmpc-%')).order_by(Client.code.desc()).first()
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
    last_material = Material.query.filter(Material.code.like('tmpm-%')).order_by(Material.code.desc()).first()
    if last_material and last_material.code:
        try:
            num = int(last_material.code.split('-')[1]) + 1
        except:
            num = 1
    else:
        num = 1
    return f"tmpm-{num:05d}"

@import_export_bp.route('/import_export')
@login_required
def import_export_page():
    return render_template('import_export.html', clients=Client.query.all(), materials=Material.query.all())

@import_export_bp.route('/export_data_filter')
@login_required
def export_data_filter():
    fmt = request.args.get('format', 'excel')
    return export_data(fmt)

@import_export_bp.route('/export/<format>')
@login_required
def export_data(format):
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    client_filter = request.args.get('client')
    material_filter = request.args.get('material')
    type_filter = request.args.get('type', 'BOTH')
    
    query = Entry.query
    if start_date: query = query.filter(Entry.date >= start_date)
    if end_date: query = query.filter(Entry.date <= end_date)
    if client_filter: query = query.filter(Entry.client == client_filter)
    if material_filter: query = query.filter(Entry.material == material_filter)
    if type_filter != 'BOTH': query = query.filter(Entry.type == type_filter)
    
    entries = query.order_by(Entry.date.desc(), Entry.time.desc()).all()
    
    # Fetch all pending bills to map amounts and find orphans
    all_bills = PendingBill.query.all()
    bill_map = {b.bill_no: b for b in all_bills if b.bill_no}
    
    if format == 'pdf':
        analysis = {}
        for m in Material.query.all():
            m_entries = [e for e in entries if e.material == m.name]
            m_in = sum(e.qty for e in m_entries if e.type == 'IN')
            m_out = sum(e.qty for e in m_entries if e.type == 'OUT')
            analysis[m.name] = {'total': m_in, 'sent': m_out, 'remaining': m_in - m_out}
        
        html = render_template('pdf_report.html', entries=entries, analysis=analysis, date=date.today())
        try:
            from flask_weasyprint import HTML, render_pdf
            return render_pdf(HTML(string=html), download_name=f"inventory_analysis_{date.today()}.pdf")
        except ImportError:
            return Response(html, mimetype="text/html")

    data = []
    for e in entries:
        amount = 0
        if e.bill_no and e.bill_no in bill_map:
            amount = bill_map[e.bill_no].amount
            
        data.append({
            'Date': e.date,
            'Time': e.time,
            'Type': e.type,
            'Material': e.material,
            'ClientName': e.client or '',
            'ClientCode': e.client_code or '',
            'Quantity': e.qty,
            'bill_no': e.bill_no or '',
            'nimbus_no': e.nimbus_no or '',
            'Captured By': e.created_by or 'System',
            'Amount': amount
        })
        
    # Add orphaned bills (Bills that exist in PendingBill but have no Entry)
    # This ensures "Export = Import" preserves financial-only records
    entry_bill_nos = set(e.bill_no for e in entries if e.bill_no)
    
    for b in all_bills:
        if b.bill_no and b.bill_no not in entry_bill_nos:
            # Apply filters to orphaned bills if possible
            b_date = b.created_at[:10] if b.created_at and len(b.created_at) >= 10 else ''
            if start_date and b_date < start_date: continue
            if end_date and b_date > end_date: continue
            if client_filter and b.client_name != client_filter: continue
            
            data.append({
                'Date': b_date,
                'Time': b.created_at[11:] if b.created_at and len(b.created_at) > 11 else '00:00:00',
                'Type': 'OUT', # Default to OUT for sales bills
                'Material': '', # No material for financial-only bill
                'ClientName': b.client_name,
                'ClientCode': b.client_code,
                'Quantity': 0,
                'bill_no': b.bill_no,
                'nimbus_no': b.nimbus_no,
                'Captured By': b.created_by or 'System',
                'Amount': b.amount
            })
            
    df = pd.DataFrame(data)
    
    if format == 'excel':
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        return send_file(output, as_attachment=True, download_name=f"inventory_report_{date.today()}.xlsx")
    
    elif format == 'csv':
        return Response(df.to_csv(index=False), mimetype="text/csv", 
                        headers={"Content-disposition": f"attachment; filename=inventory_report_{date.today()}.csv"})
    
    return redirect(url_for('tracking'))

import threading
from flask import jsonify

import_progress = {'current': 0, 'total': 0, 'done': False}

@import_export_bp.route('/import_status')
@login_required
def get_import_status():
    return jsonify(import_progress)

@import_export_bp.route('/import_data_ajax', methods=['POST'])
@login_required
def import_data_ajax():
    global import_progress
    file = request.files.get('file')
    mode = request.form.get('mode')
    import_date = request.form.get('date')
    
    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'No file provided'})

    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)
        
        import_progress = {'current': 0, 'total': len(df), 'done': False}
        
        if mode == 'daily' and import_date:
            Entry.query.filter_by(date=import_date).delete()

        today_str = date.today().strftime('%Y-%m-%d')
        now_time_str = datetime.now().strftime('%H:%M:%S')

        for i, row in df.iterrows():
            mat_name = str(row.get('Material', '')).strip()
            bill_no = str(row.get('bill_no', row.get('Bill No', ''))).strip()
            if pd.isna(row.get('bill_no')) and pd.isna(row.get('Bill No')):
                bill_no = None
            
            # Allow import if material is missing BUT bill_no exists (Financial Record)
            if (not mat_name or mat_name.lower() == 'nan') and not bill_no:
                import_progress['current'] = i + 1
                continue
            
            client_name = str(row.get('ClientName', '')).strip() if pd.notna(row.get('ClientName')) else None
            client_code = str(row.get('ClientCode', '')).strip() if pd.notna(row.get('ClientCode')) else None
            qty = float(row.get('Quantity', 0))
            amount = float(row.get('Amount', 0)) if pd.notna(row.get('Amount')) else 0
            row_type = str(row.get('Type', 'IN')).strip().upper()
            
            if not row_type or row_type == 'NAN':
                row_type = 'OUT' if client_name and client_name != '' else 'IN'

            if mat_name and mat_name.lower() != 'nan':
                mat = Material.query.filter_by(name=mat_name).first()
                if not mat:
                    mat_code = generate_material_code()
                    mat = Material(name=mat_name, code=mat_code)
                    db.session.add(mat)
                    db.session.flush()

            if client_name and client_name != '':
                # Clean up name for comparison
                clean_name = client_name.strip().upper()
                existing_client = Client.query.filter(
                    (func.upper(Client.name) == clean_name) | 
                    (Client.code == client_code if client_code else False)
                ).first()
                
                if not existing_client:
                    if not client_code or client_code == '' or client_code == 'nan':
                        client_code = generate_client_code()
                    existing_client = Client(name=client_name, code=client_code)
                    db.session.add(existing_client)
                    db.session.flush()
                else:
                    client_code = existing_client.code
                    # Update name if it was previously less complete
                    if len(client_name) > len(existing_client.name):
                        existing_client.name = client_name
            
            row_date = str(row.get('Date', '')).strip()
            if not row_date or row_date.lower() == 'nan':
                row_date = import_date or today_str
            
            row_time = str(row.get('Time', '')).strip()
            if not row_time or row_time.lower() == 'nan':
                row_time = now_time_str
            
            # Create/Update PendingBill for every entry with a bill_no
            if bill_no and client_code:
                existing_pb = PendingBill.query.filter_by(bill_no=bill_no, client_code=client_code).first()
                if not existing_pb:
                    db.session.add(PendingBill(
                        client_code=client_code,
                        client_name=client_name,
                        bill_no=bill_no,
                        nimbus_no=str(row.get('nimbus_no', row.get('Nimbus No', ''))).strip() if pd.notna(row.get('nimbus_no')) or pd.notna(row.get('Nimbus No')) else None,
                        amount=amount, 
                        reason="Auto-created from delivery",
                        created_at=row_date,
                        created_by=str(row.get('Captured By', current_user.username))
                    ))
                elif amount > 0:
                    # Update amount if provided in import
                    existing_pb.amount = amount

            db.session.add(Entry(
                date=row_date, time=row_time, type=row_type,
                material=mat_name if mat_name and mat_name.lower() != 'nan' else '', 
                client=client_name if client_name != '' else None,
                client_code=client_code if client_code != '' else None,
                qty=qty, 
                bill_no=bill_no,
                nimbus_no=str(row.get('nimbus_no', row.get('Nimbus No', ''))).strip() if pd.notna(row.get('nimbus_no')) or pd.notna(row.get('Nimbus No')) else None,
                created_by=str(row.get('Captured By', row.get('CapturedBy', current_user.username))).strip()
            ))
            
            import_progress['current'] = i + 1
            if (i + 1) % 200 == 0:
                db.session.commit()
        
        db.session.commit()
        import_progress['done'] = True
        return jsonify({'success': True, 'rows': len(df)})
    except Exception as e:
        import_progress['done'] = True
        return jsonify({'success': False, 'error': str(e)})

@import_export_bp.route('/import_pending_bills', methods=['POST'])
@login_required
def import_pending_bills():
    file = request.files.get('file')
    if not file or not file.filename:
        flash("No file selected", "danger")
        return redirect(url_for('import_export.import_export_page'))

    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)

        today_str = date.today().strftime('%Y-%m-%d')
        count = 0
        
        for _, row in df.iterrows():
            client_name = str(row.get('ClientName', '')).strip()
            if not client_name or client_name.lower() == 'nan':
                continue

            client_code = str(row.get('ClientCode', '')).strip()
            if client_code.lower() == 'nan': client_code = None

            bill_no = str(row.get('BillNo', row.get('bill_no', ''))).strip()
            nimbus_no = str(row.get('NimbusNo', row.get('nimbus_no', ''))).strip()
            amount_val = row.get('Amount', 0)
            amount = float(amount_val) if pd.notna(amount_val) and str(amount_val).strip() != '' else 0
            reason = str(row.get('Reason', '')).strip()

            # Auto-add/Verify Client
            clean_name = client_name.upper()
            client = Client.query.filter(
                (func.upper(Client.name) == clean_name) | 
                (Client.code == client_code if client_code else False)
            ).first()

            if not client:
                if not client_code or client_code == 'nan': client_code = generate_client_code()
                client = Client(name=client_name, code=client_code)
                db.session.add(client)
                db.session.flush()
            
            client_code = client.code
            
            # Sync client code back to the row if it was missing
            if not row.get('ClientCode') or str(row.get('ClientCode')).lower() == 'nan':
                client_code = client.code

            # Check if bill already exists to avoid duplicates
            existing_bill = PendingBill.query.filter_by(bill_no=bill_no, client_code=client_code).first()
            if not existing_bill:
                new_bill = PendingBill(
                    client_code=client_code,
                    client_name=client.name,
                    bill_no=bill_no,
                    nimbus_no=nimbus_no,
                    amount=amount,
                    reason=reason,
                    created_at=today_str,
                    created_by=current_user.username
                )
                db.session.add(new_bill)
                count += 1

        db.session.commit()
        flash(f"Successfully imported {count} pending bills and updated clients.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Import Failed: {str(e)}", "danger")

    return redirect(url_for('import_export.import_export_page'))
