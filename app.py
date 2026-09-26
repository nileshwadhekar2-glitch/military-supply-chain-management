"""College PBL: fictional, non-sensitive supply logistics."""
import csv
import io
import os
import secrets
import sqlite3
from datetime import date, timedelta
from functools import wraps
from pathlib import Path
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for, Response
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).parent
app = Flask(__name__)
# Keep the development secret stable across restarts; never commit it.
secret_file = ROOT / '.session-secret'
if not os.environ.get('SECRET_KEY') and not secret_file.exists():
    secret_file.write_text(secrets.token_hex(32))
    secret_file.chmod(0o600)
app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY') or secret_file.read_text(),
                  DATABASE=str(ROOT / 'database.db'), SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=timedelta(hours=4))
CATEGORIES = ['Food Supplies', 'Medical Supplies', 'Clothing', 'Communication Equipment', 'Fuel', 'General Equipment']
ROLES = ['Admin', 'Logistics Officer', 'Warehouse Staff']

def db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db

@app.teardown_appcontext
def close_db(error=None):
    if 'db' in g:
        g.db.close()

def rows(sql, args=()):
    return db().execute(sql, args).fetchall()

def one(sql, args=()):
    return db().execute(sql, args).fetchone()

def get_record(table, ident):
    result = one(f'SELECT * FROM {table} WHERE id=?', (ident,))
    if result is None:
        abort(404)
    return result

def roles(*allowed):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not g.user:
                return redirect(url_for('login'))
            if allowed and g.user['role'] not in allowed:
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorate

@app.before_request
def authenticate():
    g.user = one('SELECT * FROM users WHERE id=?', (session['user_id'],)) if session.get('user_id') else None
    session.setdefault('csrf', secrets.token_hex(24))
    if request.method == 'POST' and not secrets.compare_digest(session['csrf'], request.form.get('csrf', '')):
        abort(400, 'Invalid form token. Refresh the page and try again.')

@app.context_processor
def context():
    return dict(user=g.user, csrf=session.get('csrf'), categories=CATEGORIES, roles_list=ROLES, today=date.today().isoformat())

def text(name, maximum=150):
    value = request.form.get(name, '').strip()
    if not value or len(value) > maximum:
        raise ValueError(f'{name.replace("_", " ").title()} is required (maximum {maximum} characters).')
    return value

def number(name, minimum=0):
    try:
        value = int(request.form.get(name, ''))
    except ValueError:
        raise ValueError(f'{name.replace("_", " ").title()} must be a whole number.')
    if value < minimum or value > 100000000:
        raise ValueError(f'{name.replace("_", " ").title()} must be between {minimum} and 100000000.')
    return value

def choice(name, allowed):
    value = text(name)
    if value not in allowed:
        raise ValueError(f'Invalid {name}.')
    return value

def iso_date(name, optional=False):
    value = request.form.get(name, '')
    if optional and not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError('Enter a valid date.')

def activity(message):
    db().execute('INSERT INTO activities(message,user_id) VALUES (?,?)', (message, g.user['id']))

def warehouse_scope(warehouse_id):
    if g.user['role'] == 'Warehouse Staff' and g.user['warehouse_id'] != warehouse_id:
        abort(403)

def capacity_check(warehouse_id, additional):
    w = get_record('warehouses', warehouse_id)
    current = one('SELECT COALESCE(SUM(quantity),0) n FROM supplies WHERE warehouse_id=?', (warehouse_id,))['n']
    if w['status'] != 'Active' or current + additional > w['capacity']:
        raise ValueError('Warehouse is inactive or has insufficient capacity.')

def inventory():
    query = 'SELECT s.*,w.name warehouse FROM supplies s JOIN warehouses w ON w.id=s.warehouse_id WHERE 1=1'
    args = []
    if g.user['role'] == 'Warehouse Staff':
        query += ' AND s.warehouse_id=?'; args.append(g.user['warehouse_id'])
    for field, column in [('warehouse', 's.warehouse_id'), ('category', 's.category'), ('status', 's.status')]:
        if request.args.get(field):
            query += f' AND {column}=?'; args.append(request.args[field])
    if request.args.get('q'):
        query += ' AND s.name LIKE ?'; args.append('%' + request.args['q'] + '%')
    return rows(query + ' ORDER BY s.id', args)

def request_rows():
    query = '''SELECT r.*,s.name supply,s.unit,w.name warehouse,u.name requester_name,
               v.vehicle_number FROM requests r JOIN supplies s ON s.id=r.supply_id
               JOIN warehouses w ON w.id=r.source_warehouse JOIN users u ON u.id=r.requester
               LEFT JOIN vehicles v ON v.id=r.vehicle_id WHERE 1=1'''
    args = []
    if g.user['role'] == 'Warehouse Staff':
        query += ' AND r.source_warehouse=?'; args.append(g.user['warehouse_id'])
    for key, column in [('warehouse', 'r.source_warehouse'), ('category', 's.category'), ('status', 'r.status')]:
        if request.args.get(key):
            query += f' AND {column}=?'; args.append(request.args[key])
    if request.args.get('date'):
        query += ' AND date(r.request_date)=?'; args.append(request.args['date'])
    return rows(query + ' ORDER BY r.id DESC', args)

def alerts_data():
    alerts = []
    limit = (date.today() + timedelta(days=30)).isoformat()
    for s in inventory():
        if s['quantity'] < s['minimum_stock']:
            alerts.append(('Low stock', f"LOW STOCK ALERT · {s['name']} — {s['quantity']} {s['unit']} remaining", f"low:{s['id']}"))
        if s['expiry_date'] and s['expiry_date'] <= limit:
            label = 'Expired' if s['expiry_date'] < date.today().isoformat() else 'Near expiry'
            alerts.append((label, f"EXPIRY ALERT · {s['name']} — {s['expiry_date']}", f"expiry:{s['id']}"))
    for r in request_rows():
        if r['status'] == 'Pending':
            alerts.append(('Pending', f"Request REQ-{r['id']:04d} awaits approval", f"pending:{r['id']}"))
        if r['status'] == 'In Transit' and r['expected_date'] < date.today().isoformat():
            alerts.append(('Delayed', f"Request REQ-{r['id']:04d} is overdue at {r['destination']}", f"delay:{r['id']}"))
    return alerts

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = one('SELECT * FROM users WHERE email=?', (request.form.get('email', '').strip().lower(),))
        if u and check_password_hash(u['password'], request.form.get('password', '')):
            session.clear(); session['user_id'] = u['id']; session.permanent = True
            return redirect(url_for('dashboard'))
        flash('Email or password is incorrect.', 'danger')
    return render_template('login.html', title='Sign in')

@app.post('/logout')
@roles()
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.get('/')
@roles()
def dashboard():
    supplies = inventory(); reqs = request_rows(); alerts = alerts_data()
    warehouses = rows('SELECT * FROM warehouses') if g.user['role'] != 'Warehouse Staff' else rows('SELECT * FROM warehouses WHERE id=?', (g.user['warehouse_id'],))
    counts = [len(supplies), len(warehouses), sum(r['status']=='Pending' for r in reqs), sum(r['status']=='In Transit' for r in reqs), sum(r['status']=='Delivered' for r in reqs), sum(s['quantity'] < s['minimum_stock'] for s in supplies)]
    chart = {c:sum(s['quantity'] for s in supplies if s['category']==c) for c in CATEGORIES}
    statuses = {s:sum(r['status']==s for r in reqs) for s in ['Pending','Approved','Rejected','In Transit','Delivered']}
    activities = rows('SELECT * FROM activities ORDER BY id DESC LIMIT 6') if g.user['role'] != 'Warehouse Staff' else rows('SELECT * FROM activities WHERE user_id=? ORDER BY id DESC LIMIT 6', (g.user['id'],))
    return render_template('dashboard.html', title='Overview', counts=counts, chart=chart, statuses=statuses, supplies=supplies, reqs=reqs[:5], alerts=alerts[:4], activities=activities)

@app.get('/inventory')
@roles()
def inventory_page():
    return render_template('inventory.html', title='Inventory', supplies=inventory(), warehouses=rows('SELECT * FROM warehouses'))

@app.route('/supplies/add', methods=['GET','POST'])
@app.route('/supplies/<int:ident>/edit', methods=['GET','POST'])
@roles('Admin')
def supply_form(ident=None):
    supply = get_record('supplies', ident) if ident else None
    if request.method == 'POST':
        try:
            name=text('name'); category=choice('category', CATEGORIES); quantity=number('quantity'); unit=text('unit',30)
            warehouse=number('warehouse_id',1); minimum=number('minimum_stock'); expiry=iso_date('expiry_date',True); status=choice('status',['Active','Inactive'])
            if supply and one("SELECT id FROM requests WHERE supply_id=? AND status IN ('Pending','Approved','In Transit')",(ident,)):
                if warehouse != supply['warehouse_id'] or quantity != supply['quantity']:
                    raise ValueError('Use stock movements for quantities; warehouse cannot change while requests are open.')
            capacity_check(warehouse,quantity-(supply['quantity'] if supply and supply['warehouse_id']==warehouse else 0))
            with db():
                values=(name,category,quantity,unit,warehouse,minimum,expiry,status)
                if supply:
                    db().execute('UPDATE supplies SET name=?,category=?,quantity=?,unit=?,warehouse_id=?,minimum_stock=?,expiry_date=?,status=? WHERE id=?', values+(ident,))
                else:
                    ident=db().execute('INSERT INTO supplies(name,category,quantity,unit,warehouse_id,minimum_stock,expiry_date,status) VALUES (?,?,?,?,?,?,?,?)',values).lastrowid
                delta=quantity-(supply['quantity'] if supply else 0)
                db().execute('INSERT INTO stock_movements(supply_id,user_id,quantity,reason) VALUES (?,?,?,?)',(ident,g.user['id'],delta,'Supply created / edited'))
                activity(f'Supply {name} saved')
            flash('Supply saved.', 'success'); return redirect(url_for('inventory_page'))
        except (ValueError, sqlite3.IntegrityError) as e:
            flash(str(e),'danger')
    return render_template('edit_supply.html' if supply else 'add_supply.html', title='Edit supply' if supply else 'Add supply', supply=supply, warehouses=rows('SELECT * FROM warehouses'))

@app.post('/supplies/<int:ident>/delete')
@roles('Admin')
def delete_supply(ident):
    get_record('supplies',ident)
    if one('SELECT id FROM requests WHERE supply_id=?',(ident,)):
        flash('This supply has request history. Mark it inactive instead.', 'warning')
    else:
        with db():
            db().execute('DELETE FROM stock_movements WHERE supply_id=?',(ident,))
            db().execute('DELETE FROM supplies WHERE id=?',(ident,)); activity(f'Supply #{ident} deleted')
        flash('Supply deleted.', 'success')
    return redirect(url_for('inventory_page'))

@app.post('/supplies/<int:ident>/stock')
@roles('Admin','Warehouse Staff')
def stock(ident):
    s=get_record('supplies',ident); warehouse_scope(s['warehouse_id'])
    try:
        amount=number('amount',1); direction=choice('direction',['Incoming','Outgoing']); reason=text('reason')
        delta=amount if direction=='Incoming' else -amount
        with db():
            # Acquire a write lock before checking quantities and capacity.
            db().execute('UPDATE supplies SET quantity=quantity WHERE id=?',(ident,))
            s=get_record('supplies',ident)
            if s['quantity']+delta < 0: raise ValueError('Insufficient stock.')
            capacity_check(s['warehouse_id'],delta)
            db().execute('UPDATE supplies SET quantity=quantity+? WHERE id=?',(delta,ident))
            db().execute('INSERT INTO stock_movements(supply_id,user_id,quantity,reason) VALUES (?,?,?,?)',(ident,g.user['id'],delta,reason))
            activity(f'{direction}: {amount} {s["unit"]} of {s["name"]}')
        flash('Stock movement recorded.', 'success')
    except ValueError as e: flash(str(e),'danger')
    return redirect(url_for('inventory_page'))

@app.route('/warehouses',methods=['GET','POST'])
@roles()
def warehouses_page():
    if request.method=='POST':
        if g.user['role']!='Admin': abort(403)
        try:
            ident=request.form.get('id'); name=text('name'); location=text('location'); capacity=number('capacity',1)
            manager=text('manager'); contact=text('contact'); status=choice('status',['Active','Inactive'])
            if ident:
                get_record('warehouses',int(ident))
                used=one('SELECT COALESCE(SUM(quantity),0) n FROM supplies WHERE warehouse_id=?',(ident,))['n']
                if capacity<used: raise ValueError('Capacity cannot be lower than current stock.')
            with db():
                if ident: db().execute('UPDATE warehouses SET name=?,location=?,capacity=?,manager=?,contact=?,status=? WHERE id=?',(name,location,capacity,manager,contact,status,ident))
                else: db().execute('INSERT INTO warehouses(name,location,capacity,manager,contact,status) VALUES (?,?,?,?,?,?)',(name,location,capacity,manager,contact,status))
                activity(f'Warehouse {name} saved')
            flash('Warehouse saved.','success'); return redirect(url_for('warehouses_page'))
        except (ValueError,sqlite3.IntegrityError) as e: flash(str(e),'danger')
    query='SELECT w.*,COALESCE(SUM(s.quantity),0) current_stock FROM warehouses w LEFT JOIN supplies s ON s.warehouse_id=w.id'
    args=()
    if g.user['role']=='Warehouse Staff': query+=' WHERE w.id=?'; args=(g.user['warehouse_id'],)
    ws=rows(query+' GROUP BY w.id',args)
    edit=get_record('warehouses',request.args['edit']) if request.args.get('edit') and g.user['role']=='Admin' else None
    return render_template('warehouses.html',title='Warehouses',warehouses=ws,edit=edit)

@app.post('/warehouses/<int:ident>/delete')
@roles('Admin')
def delete_warehouse(ident):
    try:
        with db(): db().execute('DELETE FROM warehouses WHERE id=?',(ident,)); activity(f'Warehouse #{ident} deleted')
        flash('Warehouse deleted.','success')
    except sqlite3.IntegrityError: flash('Warehouse is linked to users, supplies or requests. Reassign these records first.','warning')
    return redirect(url_for('warehouses_page'))

@app.route('/requests',methods=['GET','POST'])
@roles('Admin','Logistics Officer')
def requests_page():
    if request.method=='POST':
        try:
            s=get_record('supplies',number('supply_id',1)); quantity=number('quantity',1); destination=text('destination'); priority=choice('priority',['Routine','High','Urgent'])
            if s['status']!='Active': raise ValueError('Supply is inactive.')
            if s['expiry_date'] and s['expiry_date']<date.today().isoformat(): raise ValueError('Expired supplies cannot be requested.')
            with db():
                db().execute('INSERT INTO requests(requester,supply_id,quantity,source_warehouse,destination,priority) VALUES (?,?,?,?,?,?)',(g.user['id'],s['id'],quantity,s['warehouse_id'],destination,priority))
                activity(f'Request created for {s["name"]}')
            flash('Request submitted for approval.','success'); return redirect(url_for('requests_page'))
        except ValueError as e: flash(str(e),'danger')
    return render_template('requests.html',title='Supply requests',reqs=request_rows(),supplies=inventory(),vehicles=rows("SELECT * FROM vehicles WHERE status='Available'"))

@app.get('/approvals')
@roles('Admin','Logistics Officer')
def approvals():
    return render_template('approvals.html',title='Request approvals',reqs=[r for r in request_rows() if r['status']=='Pending'], supplies=inventory(),vehicles=[])

@app.post('/requests/<int:ident>/action')
@roles('Admin','Logistics Officer')
def request_action(ident):
    try:
        action=choice('action',['Approve','Reject','Dispatch','Deliver'])
        with db():
            db().execute('UPDATE requests SET status=status WHERE id=?',(ident,))
            r=get_record('requests',ident); s=get_record('supplies',r['supply_id'])
            if action in ['Approve','Reject']:
                if r['status']!='Pending': raise ValueError('Only pending requests can be reviewed.')
                if action=='Approve' and (s['status']!='Active' or s['quantity']<r['quantity']): raise ValueError('Insufficient or inactive stock. Replenish before approval.')
                status='Approved' if action=='Approve' else 'Rejected'
                db().execute('UPDATE requests SET status=? WHERE id=?',(status,ident))
            elif action=='Dispatch':
                if r['status']!='Approved': raise ValueError('Approve the request before dispatch.')
                v=get_record('vehicles',number('vehicle_id',1)); expected=iso_date('expected_date')
                if expected<date.today().isoformat(): raise ValueError('Expected delivery cannot be in the past.')
                if v['status']!='Available': raise ValueError('Vehicle is already assigned.')
                if s['status']!='Active' or (s['expiry_date'] and s['expiry_date']<=expected): raise ValueError('Supply is inactive or expires before delivery.')
                if get_record('warehouses',r['source_warehouse'])['status']!='Active': raise ValueError('Source warehouse is inactive.')
                result=db().execute('UPDATE supplies SET quantity=quantity-? WHERE id=? AND quantity>=?',(r['quantity'],s['id'],r['quantity']))
                if result.rowcount!=1: raise ValueError('Insufficient stock to dispatch.')
                db().execute("UPDATE requests SET status='In Transit',vehicle_id=?,dispatch_date=?,expected_date=? WHERE id=?",(v['id'],date.today().isoformat(),expected,ident))
                db().execute("UPDATE vehicles SET status='In Transit',source=?,destination=?,dispatch_date=?,expected_date=? WHERE id=?",(str(r['source_warehouse']),r['destination'],date.today().isoformat(),expected,v['id']))
                db().execute('INSERT INTO stock_movements(supply_id,user_id,quantity,reason) VALUES (?,?,?,?)',(s['id'],g.user['id'],-r['quantity'],f'Dispatch REQ-{ident:04d}'))
            else:
                if r['status']!='In Transit': raise ValueError('Only dispatched requests can be delivered.')
                db().execute("UPDATE requests SET status='Delivered',delivered_date=? WHERE id=?",(date.today().isoformat(),ident))
                db().execute("UPDATE vehicles SET status='Available' WHERE id=?",(r['vehicle_id'],))
            db().execute('INSERT INTO request_events(request_id,status) VALUES (?,?)',(ident,action))
            activity(f'REQ-{ident:04d}: {action}')
        flash('Request updated.','success')
    except ValueError as e: flash(str(e),'danger')
    return redirect(url_for('requests_page'))

@app.route('/transportation',methods=['GET','POST'])
@roles('Admin','Logistics Officer')
def transportation():
    if request.method=='POST':
        try:
            values=(text('vehicle_number',30),text('vehicle_type',50),text('driver_name',80))
            ident=request.form.get('id')
            with db():
                if ident:
                    v=get_record('vehicles',ident)
                    if v['status']=='In Transit': raise ValueError('Vehicle details cannot change during delivery.')
                    db().execute('UPDATE vehicles SET vehicle_number=?,vehicle_type=?,driver_name=? WHERE id=?',values+(ident,))
                else: db().execute('INSERT INTO vehicles(vehicle_number,vehicle_type,driver_name) VALUES (?,?,?)',values)
                activity(f'Vehicle {values[0]} saved')
            flash('Vehicle saved.','success'); return redirect(url_for('transportation'))
        except (ValueError,sqlite3.IntegrityError): flash('Check the vehicle details; vehicle numbers must be unique and assigned vehicles cannot be edited.','danger')
    edit=get_record('vehicles',request.args['edit']) if request.args.get('edit') else None
    return render_template('transportation.html',title='Transportation',vehicles=rows('SELECT v.*,w.name source_name FROM vehicles v LEFT JOIN warehouses w ON w.id=v.source'),edit=edit)

@app.get('/tracking')
@roles()
def tracking():
    reqs=request_rows()
    if request.args.get('id'): reqs=[r for r in reqs if str(r['id'])==request.args['id']]
    return render_template('tracking.html',title='Delivery tracking',reqs=reqs,events=rows('SELECT * FROM request_events ORDER BY id'))

@app.route('/alerts',methods=['GET','POST'])
@roles()
def alerts():
    data=alerts_data()
    with db():
        for kind,message,key in data:
            db().execute('INSERT OR IGNORE INTO notifications(user_id,alert_key,message,type) VALUES (?,?,?,?)',(g.user['id'],key,message,kind))
            db().execute('UPDATE notifications SET message=? WHERE user_id=? AND alert_key=?',(message,g.user['id'],key))
        if request.method=='POST':
            db().execute('UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?',(request.form.get('id'),g.user['id']))
    keys={a[2] for a in data}
    ns=[n for n in rows('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC',(g.user['id'],)) if n['alert_key'] in keys]
    return render_template('alerts.html',title='Alerts & notifications',notifications=ns)

@app.get('/reports')
@roles('Admin','Logistics Officer')
def reports():
    supplies=inventory(); reqs=request_rows()
    if request.args.get('export')=='csv':
        stream=io.StringIO(); writer=csv.writer(stream)
        writer.writerow(['Record','ID','Name / Destination','Quantity','Status'])
        def safe(v):
            return "'"+str(v) if str(v).startswith(('=','+','-','@','\t','\r')) else v
        for s in supplies: writer.writerow([safe(v) for v in ['Supply',s['id'],s['name'],s['quantity'],s['status']]])
        for r in reqs: writer.writerow([safe(v) for v in ['Request',r['id'],r['destination'],r['quantity'],r['status']]])
        return Response(stream.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=logistics-report.csv'})
    return render_template('reports.html',title='Reports',supplies=supplies,reqs=reqs,warehouses=rows('SELECT * FROM warehouses'),vehicles=rows('SELECT * FROM vehicles'))

@app.route('/users',methods=['GET','POST'])
@roles('Admin')
def users_page():
    if request.method=='POST':
        try:
            ident=request.form.get('id'); name=text('name'); email=text('email').lower(); role=choice('role',ROLES)
            if '@' not in email or '.' not in email.split('@')[-1]: raise ValueError('Enter a valid email address.')
            warehouse=number('warehouse_id',1) if role=='Warehouse Staff' else None
            if warehouse: get_record('warehouses',warehouse)
            if ident and int(ident)==g.user['id'] and role!='Admin': raise ValueError('You cannot remove your own administrator role.')
            password=request.form.get('password','')
            if (not ident or password) and len(password)<8: raise ValueError('Password must contain at least 8 characters.')
            with db():
                if ident:
                    get_record('users',ident)
                    db().execute('UPDATE users SET name=?,email=?,role=?,warehouse_id=? WHERE id=?',(name,email,role,warehouse,ident))
                    if password: db().execute('UPDATE users SET password=? WHERE id=?',(generate_password_hash(password),ident))
                else: db().execute('INSERT INTO users(name,email,password,role,warehouse_id) VALUES (?,?,?,?,?)',(name,email,generate_password_hash(password),role,warehouse))
                activity(f'User {name} saved')
            flash('User saved.','success'); return redirect(url_for('users_page'))
        except (ValueError,sqlite3.IntegrityError) as e: flash('Email already exists.' if isinstance(e,sqlite3.IntegrityError) else str(e),'danger')
    edit=get_record('users',request.args['edit']) if request.args.get('edit') else None
    return render_template('users.html',title='User management',users=rows('SELECT u.*,w.name warehouse FROM users u LEFT JOIN warehouses w ON w.id=u.warehouse_id'),warehouses=rows('SELECT * FROM warehouses'),edit=edit)

@app.post('/users/<int:ident>/delete')
@roles('Admin')
def delete_user(ident):
    if ident==g.user['id']: flash('You cannot delete your own account.','warning')
    else:
        try:
            with db(): db().execute('DELETE FROM users WHERE id=?',(ident,)); activity(f'User #{ident} deleted')
            flash('User deleted.','success')
        except sqlite3.IntegrityError: flash('User has audit or request history and cannot be deleted.','warning')
    return redirect(url_for('users_page'))

@app.route('/profile',methods=['GET','POST'])
@roles()
def profile():
    if request.method=='POST':
        try:
            if not check_password_hash(g.user['password'],request.form.get('current_password','')): raise ValueError('Current password is incorrect.')
            password=text('password')
            if len(password)<8: raise ValueError('Use at least 8 characters.')
            with db(): db().execute('UPDATE users SET password=? WHERE id=?',(generate_password_hash(password),g.user['id']))
            flash('Password changed.','success')
        except ValueError as e: flash(str(e),'danger')
    return render_template('profile.html',title='My profile')

@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
def error_page(error):
    return render_template('error.html',title=str(error.code),error=error),error.code

@app.cli.command('init-db')
def init_db():
    """Create schema and seed a new database; never erase existing records."""
    db().executescript((ROOT/'schema.sql').read_text())
    if one('SELECT id FROM users LIMIT 1'):
        print('Database already initialized; data preserved.'); return
    with db():
        for name,location,capacity,manager in [('Central Supply Depot','Pune · Training Campus',15000,'Aarav Mehta'),('Northern Storage Hub','Chandigarh · Demo Campus',10000,'Priya Sharma'),('Southern Logistics Center','Bengaluru · Demo Campus',12000,'Rohan Das')]:
            db().execute('INSERT INTO warehouses(name,location,capacity,manager,contact,status) VALUES (?,?,?,?,?,?)',(name,location,capacity,manager,'demo@example.com','Active'))
        for name,email,role,w in [('Alex Morgan','admin@demo.local','Admin',None),('Priya Sharma','officer@demo.local','Logistics Officer',None),('Aarav Mehta','staff@demo.local','Warehouse Staff',1)]:
            db().execute('INSERT INTO users(name,email,password,role,warehouse_id) VALUES (?,?,?,?,?)',(name,email,generate_password_hash('Demo@12345'),role,w))
        for name,cat,qty,unit,w,minimum,days in [('Ready-to-eat meal packs',0,2400,'packs',1,500,180),('First-aid kits',1,84,'kits',1,100,20),('Field uniforms',2,1250,'sets',2,200,None),('Handheld radios',3,180,'units',2,50,None),('Diesel fuel',4,3200,'litres',3,800,None),('Water purification tablets',1,65,'boxes',3,100,12),('Bottled drinking water',0,4200,'bottles',1,1000,90),('Utility tool kits',5,320,'kits',3,60,None)]:
            expiry=(date.today()+timedelta(days=days)).isoformat() if days else None
            db().execute('INSERT INTO supplies(name,category,quantity,unit,warehouse_id,minimum_stock,expiry_date,status) VALUES (?,?,?,?,?,?,?,?)',(name,CATEGORIES[cat],qty,unit,w,minimum,expiry,'Active'))
        for plate,kind,driver in [('DEMO-101','Cargo truck','Dev Patel'),('DEMO-202','Delivery van','Maya Rao'),('DEMO-303','Utility truck','Sam Wilson')]:
            db().execute('INSERT INTO vehicles(vehicle_number,vehicle_type,driver_name) VALUES (?,?,?)',(plate,kind,driver))
        for sid,qty,warehouse,dest,priority,status in [(1,200,1,'Training Center Alpha','Routine','Pending'),(2,20,1,'Campus Medical Unit','Urgent','Pending'),(3,100,2,'Training Center Bravo','High','Approved'),(8,30,3,'Maintenance Workshop','Routine','Delivered'),(7,300,1,'Training Center Charlie','High','In Transit')]:
            db().execute('INSERT INTO requests(requester,supply_id,quantity,source_warehouse,destination,priority,status) VALUES (2,?,?,?,?,?,?)',(sid,qty,warehouse,dest,priority,status))
        now=date.today().isoformat(); future=(date.today()+timedelta(days=2)).isoformat()
        db().execute("UPDATE requests SET vehicle_id=1,dispatch_date=?,expected_date=? WHERE id=5",(now,future))
        db().execute("UPDATE vehicles SET status='In Transit',source='1',destination='Training Center Charlie',dispatch_date=?,expected_date=? WHERE id=1",(now,future))
        db().execute('UPDATE requests SET vehicle_id=2,dispatch_date=?,expected_date=?,delivered_date=? WHERE id=4',(now,now,now))
        for sid,qty,rid in [(8,30,4),(7,300,5)]:
            db().execute('UPDATE supplies SET quantity=quantity-? WHERE id=?',(qty,sid))
            db().execute('INSERT INTO stock_movements(supply_id,user_id,quantity,reason) VALUES (?,1,?,?)',(sid,-qty,f'Sample dispatch REQ-{rid:04d}'))
        db().execute("INSERT INTO activities(message,user_id) VALUES ('Demo workspace initialized',1)")
    print('Database created with fictional demo data.')

if __name__=='__main__':
    app.run(host='127.0.0.1',port=5000,debug=False)
