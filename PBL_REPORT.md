# PBL Report: Military Supply Chain Management System

## Problem statement

Manual stock registers and separate spreadsheets make it difficult to know available quantities, identify shortages, approve requests and confirm deliveries. Repeated data entry can cause inconsistencies, expired supplies may be overlooked, and responsibilities may be unclear. This project models a fictional logistics organization and addresses these inventory-management problems without operational or sensitive military information.

## Proposed solution

Build a browser-based application called SupplyLine using Python Flask, SQLite, HTML, CSS, JavaScript and Bootstrap 5. Three roles share a central database with different permissions. Supplies are stored at warehouses, requested by logistics personnel, approved, assigned to vehicles and marked delivered. Stock is deducted atomically at dispatch. Dashboard indicators and alerts summarize the current situation.

## Objectives

1. Maintain accurate, nonnegative supply quantities and warehouse records.
2. Track requests from creation through approval, dispatch and delivery.
3. Separate administrative, logistics and warehouse responsibilities.
4. Highlight low stock, approaching expiry, pending requests and delays.
5. Provide filterable reports and exportable records.
6. Demonstrate relational database design, CRUD, authentication and transaction handling in a beginner-friendly project.

## Main features

- Secure login, hashed passwords, sessions, CSRF protection and role checks.
- Supply creation, editing, deletion, categories, minimum quantities and expiry dates.
- Warehouse management, capacity checks and computed stock totals.
- Incoming and outgoing stock movement records.
- Request creation, approval, rejection and priority.
- Vehicle registration, assignment, dispatch and delivery confirmation.
- Five-step delivery visualization and stored request events.
- Automatic alerts with individual acknowledgement.
- Dashboard charts, recent activities and summary cards.
- Date, warehouse, category and status report filters with CSV export.
- User management, warehouse staff assignment and password changes.
- Responsive layout and locally bundled Bootstrap for offline demonstrations.

## Methodology

1. **Requirements:** identify the three user roles and permitted actions.
2. **Design:** define the ER relationships and request state transitions.
3. **Database:** create primary keys, foreign keys, CHECK constraints and indexes.
4. **Backend:** implement authentication, validation and parameterized queries.
5. **Frontend:** create shared templates, forms, tables, charts and status labels.
6. **Integration:** connect dispatch to stock reduction and vehicle availability.
7. **Testing:** use isolated databases to check normal workflows and rejected operations.
8. **Demonstration:** use only seeded fictional data and present the complete lifecycle.

## Advantages

The application gives users a shared view of stock and request status, reduces duplicate record keeping, makes shortages visible, and prevents invalid dispatches. It is inexpensive to run and easy to demonstrate on one laptop. The compact technology stack is suitable for explaining application architecture and relational concepts during a second-year viva.

## Testing summary

The automated suite covers page rendering, login and roles, assigned warehouse isolation, CSRF rejection, CRUD, alerts, seed preservation, password changes, approval/dispatch/delivery, repeat dispatch and transaction rollback. Browser inspection covers the login and dashboard at mobile and desktop layouts. Tests demonstrate the implemented rules, rather than certifying production readiness.

## Limitations

This is an academic local application. Capacity is a simplified sum of quantities rather than a physical space calculation. Requests contain one supply line. Approval does not reserve stock; availability is rechecked at dispatch. Delivery confirms receipt without adding stock to a destination warehouse. There are no real-time location services, external integrations or production identity services. Date filters apply to requests, while inventory reports show current stock.

## Future scope

- Multiple line items per request and partial deliveries.
- Batch-level stock and first-expiry-first-out allocation.
- Reservation of inventory during approval.
- Receipt confirmation into destination warehouse inventory.
- Weight/volume-based capacity and consistent unit conversion.
- Barcode scanning for stock entry.
- Pagination, larger-database support and richer audit reports.
- Login rate limiting, password recovery and stronger session revocation.
- Automated backups and production hosting with HTTPS.
- Notification preferences and email reminders for fictional logistics workflows.

## Conclusion

SupplyLine demonstrates how a relational web application can connect inventory, warehouses, requests and transportation. Its central contribution is a consistent request-to-delivery workflow with validated stock changes and role-based access. It is a practical foundation for learning Flask, SQL, authentication and responsive interface design.

## Possible viva questions and answers

**1. What problem does the project solve?**  
It combines stock records, requests and delivery information in one system so users can identify shortages and follow supply movement.

**2. Why did you choose Flask?**  
Flask has a small core and straightforward routes. It lets a student clearly see how an HTTP request reaches Python logic and produces an HTML response.

**3. Why SQLite?**  
SQLite stores relational data in one local file and needs no separate database server. It suits a classroom demonstration with a small number of users.

**4. What is a primary key?**  
A primary key uniquely identifies a row, such as a supply ID or request ID.

**5. What is a foreign key?**  
It references a row in another table. `supplies.warehouse_id` connects each supply to its warehouse and prevents references to nonexistent warehouses.

**6. What is CRUD?**  
Create, Read, Update and Delete. The inventory, warehouse and user screens demonstrate these operations, with restrictions for records that have history.

**7. How are passwords protected?**  
Werkzeug generates a salted password hash. Login checks the submitted password against the stored hash rather than storing or comparing readable passwords.

**8. How is a login remembered?**  
Flask stores a signed session cookie containing the user ID. The server loads the user from the database on every request and applies current role permissions.

**9. What is role-based access control?**  
Different roles receive different permissions. For example, staff may update stock only in their assigned warehouse, while only administrators manage users.

**10. Why are hidden buttons not enough for security?**  
A person can call an endpoint directly. The server must verify the role and assigned warehouse independently of the visible interface.

**11. How do you prevent SQL injection?**  
Values are passed as bound parameters instead of concatenated into SQL strings. Dynamic table and column identifiers in helpers come from fixed application code.

**12. What is CSRF protection?**  
A session-specific token is included in every POST form. Requests without the correct token are rejected, preventing another site from submitting authenticated forms blindly.

**13. When does stock decrease?**  
At dispatch. Approval alone does not change the quantity. The vehicle assignment, request status, stock deduction and movement record are committed together.

**14. What is a database transaction?**  
A transaction groups related updates into one unit. Either every update succeeds or all changes roll back, preventing a dispatched request with an unchanged stock balance.

**15. What happens if dispatch is submitted twice?**  
The first successful dispatch changes the request to In Transit. The second fails the Approved-status check, so stock is not deducted again.

**16. What happens when stock is insufficient?**  
The update checks available quantity inside the write transaction. Failure leaves stock, request and vehicle unchanged.

**17. How are low-stock alerts generated?**  
The application compares current quantity with minimum stock. An alert appears when quantity is strictly lower than the minimum.

**18. How are expiry and delay alerts generated?**  
Expiry alerts cover items expiring within 30 days or already expired. A delivery is delayed when it is still In Transit after its expected date.

**19. What is Jinja template inheritance?**  
Pages extend a common layout. Shared navigation and headers live in `base.html`, while individual pages fill its content block.

**20. Why use POST for modifications and logout?**  
GET is intended for reading resources. POST makes state changes explicit and allows consistent CSRF checks.

**21. How does responsiveness work?**  
CSS media queries change grid columns and replace the fixed sidebar with a mobile toggle. Wide tables scroll within their containers.

**22. What is the difference between authentication and authorization?**  
Authentication verifies who the user is. Authorization decides what that user is allowed to do.

**23. Why cannot some records be deleted?**  
Foreign keys and application checks preserve request and audit history. Deleting referenced rows would break traceability.

**24. How are reports filtered?**  
The backend builds queries using a fixed set of permitted filter columns and bound values. Inventory is current; request dates filter request creation.

**25. How would you scale the application?**  
Add pagination, stronger operational security, a production server, PostgreSQL, backups, monitoring and more detailed inventory models as requirements grow.
