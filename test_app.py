"""Integration checks using an isolated temporary SQLite database."""
import tempfile
import unittest
from pathlib import Path
from datetime import date, timedelta
from app import app, db, init_db

class LogisticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        app.config.update(TESTING=True,DATABASE=str(Path(self.temp.name)/'test.db'))
        self.client=app.test_client()
        result=app.test_cli_runner().invoke(args=['init-db'])
        self.assertEqual(result.exit_code,0,result.output)
    def tearDown(self): self.temp.cleanup()
    def post(self,path,data=None):
        with self.client.session_transaction() as sess: token=sess.get('csrf')
        return self.client.post(path,data={**(data or {}),'csrf':token},follow_redirects=True)
    def login(self,role='admin'):
        self.client.get('/login')
        return self.post('/login',{'email':f'{role}@demo.local','password':'Demo@12345'})
    def scalar(self,sql):
        with app.app_context(): return db().execute(sql).fetchone()[0]
    def test_all_pages_and_filters(self):
        self.login()
        for path in ['/','/inventory','/supplies/add','/supplies/1/edit','/warehouses','/warehouses?edit=1','/requests','/approvals','/transportation','/transportation?edit=2','/tracking','/tracking?id=1','/alerts','/reports','/reports?warehouse=1&category=Food+Supplies','/reports?export=csv','/users','/users?edit=2','/profile']:
            with self.subTest(path=path): self.assertEqual(self.client.get(path).status_code,200)
    def test_dispatch_atomic_and_idempotent(self):
        self.login()
        before=self.scalar('SELECT quantity FROM supplies WHERE id=3')
        payload={'action':'Dispatch','vehicle_id':'2','expected_date':(date.today()+timedelta(days=2)).isoformat()}
        self.assertIn(b'Request updated',self.post('/requests/3/action',payload).data)
        self.assertEqual(self.scalar('SELECT quantity FROM supplies WHERE id=3'),before-100)
        self.post('/requests/3/action',payload)
        self.assertEqual(self.scalar('SELECT quantity FROM supplies WHERE id=3'),before-100)
        self.assertEqual(self.scalar("SELECT status FROM vehicles WHERE id=2"),'In Transit')
        self.post('/requests/3/action',{'action':'Deliver'})
        self.assertEqual(self.scalar('SELECT status FROM requests WHERE id=3'),'Delivered')
        self.assertEqual(self.scalar('SELECT status FROM vehicles WHERE id=2'),'Available')
    def test_roles_and_csrf(self):
        self.assertEqual(self.client.get('/inventory').status_code,302)
        self.login('staff')
        for path in ['/users','/requests','/reports','/supplies/add','/transportation']:
            self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.post('/supplies/3/stock',{'direction':'Incoming','amount':'1','reason':'test'}).status_code,403)
        self.assertEqual(self.client.post('/supplies/1/stock',data={'amount':1}).status_code,400)
        self.assertNotIn(b'Field uniforms',self.client.get('/inventory').data)
        self.post('/supplies/1/stock',{'direction':'Incoming','amount':'2','reason':'Received'})
        self.assertEqual(self.scalar('SELECT quantity FROM supplies WHERE id=1'),2402)
    def test_validation_and_crud(self):
        self.login()
        supply={'name':'Blankets','category':'General Equipment','quantity':'50','unit':'sets','warehouse_id':'1','minimum_stock':'10','expiry_date':'','status':'Active'}
        self.post('/supplies/add',supply)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM supplies'),9)
        self.post('/supplies/9/edit',{**supply,'name':'Thermal blankets'})
        self.assertEqual(self.scalar('SELECT name FROM supplies WHERE id=9'),'Thermal blankets')
        self.post('/supplies/9/delete')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM supplies'),8)
        self.assertIn(b'Insufficient stock',self.post('/supplies/1/stock',{'direction':'Outgoing','amount':'9999','reason':'invalid'}).data)
        self.assertIn(b'insufficient capacity',self.post('/supplies/1/stock',{'direction':'Incoming','amount':'99999','reason':'invalid'}).data)
        self.post('/requests',{'supply_id':'1','quantity':'5','destination':'Demo Academy','priority':'High'})
        self.post('/requests/6/action',{'action':'Approve'})
        self.assertEqual(self.scalar('SELECT status FROM requests WHERE id=6'),'Approved')
        self.post('/users',{'name':'New Staff','email':'new@example.com','password':'Password123','role':'Warehouse Staff','warehouse_id':'1'})
        self.post('/users/4/delete')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM users'),3)
    def test_warehouse_and_vehicle_management(self):
        self.login()
        payload={'name':'Demo Store','location':'Example Campus','capacity':'100','manager':'Demo Manager','contact':'demo@example.com','status':'Active'}
        self.post('/warehouses',payload)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM warehouses'),4)
        self.post('/warehouses',{**payload,'id':'4','capacity':'150'})
        self.assertEqual(self.scalar('SELECT capacity FROM warehouses WHERE id=4'),150)
        self.post('/warehouses/4/delete')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM warehouses'),3)
        self.post('/transportation',{'vehicle_number':'DEMO-404','vehicle_type':'Van','driver_name':'Demo Driver'})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM vehicles'),4)
        self.post('/transportation',{'id':'4','vehicle_number':'DEMO-404','vehicle_type':'Van','driver_name':'Updated Driver'})
        self.assertEqual(self.scalar('SELECT driver_name FROM vehicles WHERE id=4'),'Updated Driver')
        self.post('/logout'); self.login('officer')
        self.assertEqual(self.client.get('/users').status_code,403)
        self.assertEqual(self.client.get('/requests').status_code,200)
    def test_expiry_and_alert_acknowledgement(self):
        self.login()
        with app.app_context(),db(): db().execute('UPDATE supplies SET expiry_date=? WHERE id=3',(date.today().isoformat(),))
        self.assertIn(b'expires before delivery',self.post('/requests/3/action',{'action':'Dispatch','vehicle_id':'2','expected_date':(date.today()+timedelta(days=2)).isoformat()}).data)
        self.assertEqual(self.scalar('SELECT status FROM requests WHERE id=3'),'Approved')
        self.client.get('/alerts')
        ident=self.scalar('SELECT id FROM notifications LIMIT 1')
        self.post('/alerts',{'id':str(ident)})
        self.assertEqual(self.scalar(f'SELECT is_read FROM notifications WHERE id={ident}'),1)
    def test_insufficient_dispatch_rolls_back(self):
        self.login()
        with app.app_context(),db(): db().execute('UPDATE supplies SET quantity=10 WHERE id=3')
        self.post('/requests/3/action',{'action':'Dispatch','vehicle_id':'2','expected_date':(date.today()+timedelta(days=2)).isoformat()})
        self.assertEqual(self.scalar('SELECT status FROM requests WHERE id=3'),'Approved')
        self.assertEqual(self.scalar('SELECT status FROM vehicles WHERE id=2'),'Available')
        self.assertEqual(self.scalar('SELECT quantity FROM supplies WHERE id=3'),10)
    def test_alerts_seed_and_password(self):
        self.login()
        self.assertIn(b'LOW STOCK ALERT',self.client.get('/alerts').data)
        self.assertIn(b'EXPIRY ALERT',self.client.get('/alerts').data)
        self.assertEqual(app.test_cli_runner().invoke(args=['init-db']).exit_code,0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM users'),3)
        self.assertNotEqual(self.scalar('SELECT password FROM users WHERE id=1'),'Demo@12345')
        self.post('/profile',{'current_password':'Demo@12345','password':'Updated123!'})
        self.post('/logout')
        self.post('/login',{'email':'admin@demo.local','password':'Updated123!'})
        self.assertEqual(self.client.get('/users').status_code,200)

if __name__=='__main__': unittest.main(verbosity=2)
