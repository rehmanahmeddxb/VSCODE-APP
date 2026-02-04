# 🏭 Ahmed Cement - Integrated CRM & Inventory System v2.0

## 🌟 Overview
**Ahmed Cement Inventory Pro** is a comprehensive, professional-grade Sales & Inventory Management System that combines the best features of both original applications with an enhanced dark-theme UI for optimal user experience.

---

## ✨ Key Features

### 🔐 **Advanced Security**
- User authentication with role-based access control
- Password hashing and secure sessions
- Granular permissions (view stock, daily transactions, history, import/export, directory management)

### 📦 **Complete Inventory Management**
- **GRN (Goods Receipt Note)** - Track incoming materials with supplier details
- **Material Management** - Auto-generated codes (tmpm-00001 format)
- **Real-time Stock Tracking** - Automatic updates on IN/OUT transactions
- **Deliveries** - Complete delivery management with automatic stock reduction
- **Material Ledger** - Complete transaction history per material

### 💼 **Comprehensive Sales System**
- **Bookings** - Multi-item bookings with client tracking
- **Direct Sales** - Quick sales entry with categorization
- **Payments** - Payment tracking with multiple methods
- **Invoicing** - Advanced invoice system with status tracking
- **Pending Bills** - Track unpaid bills and reasons
- **Client Ledger** - Complete client transaction history

### 👥 **Client Management**
- Auto-generated client codes (tmpc-000001 format)
- Client categories (General, Walking-Customer, Misc)
- Contact information and addresses
- Transaction history and balance tracking
- Client transfer functionality

### 📊 **Reporting & Analytics**
- **Dashboard** - Real-time overview with key metrics
- **Stock Summary** - Current inventory levels
- **Daily Breakdown** - Today's IN/OUT transactions
- **Transaction History** - Complete audit trail with filters
- **Unpaid Transactions** - Track receivables
- **PDF Reports** - Professional PDF generation

### 🔄 **Data Management**
- **Import/Export** - Bulk data operations
- **Database Backup** - Easy backup and restore
- **Settings** - Company settings, currency, permissions

### 🎨 **Modern UI/UX**
- **Dark Theme** - Professional dark blue/gold color scheme
- **Responsive Design** - Works on desktop, tablet, and mobile
- **Sidebar Navigation** - Collapsible sidebar with icons
- **Modal Forms** - Clean modal dialogs for data entry
- **Loading Indicators** - Visual feedback for operations
- **Flash Messages** - User-friendly success/error notifications

---

## 🚀 Installation

### Prerequisites
- Python 3.10 or higher
- pip (Python package installer)

### Step 1: Extract Files
```bash
unzip ahmed_cement_final.zip
cd ahmed_cement_final
```

### Step 2: Install Dependencies
```bash
# Recommended: Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### Step 3: Run Application
```bash
python main.py
```

The application will start on **http://localhost:5000**

### Step 4: Login
Default credentials:
- **Username:** `admin`
- **Password:** `admin123`

⚠️ **IMPORTANT:** Change the default password immediately after first login!

---

## 📱 Quick Start Guide

### First Time Setup

1. **Login** with default credentials
2. **Change Password** (Settings → Change Password)
3. **Add Materials** (Material Brands → Add Material)
   - System will auto-generate material codes (tmpm-00001, tmpm-00002, etc.)
4. **Add Clients** (Client Ledger → Add Client)
   - System will auto-generate client codes (tmpc-000001, tmpc-000002, etc.)
5. **Configure Settings** (Settings → Company Info)

### Daily Operations

#### Receiving Materials (GRN)
```
Navigation: Inventory → GRN (Receiving)
1. Click "+ Add GRN"
2. Enter supplier name
3. Add materials with quantities and prices
4. Upload bill photo (optional)
5. Submit
✅ Stock automatically increases
```

#### Recording Deliveries
```
Navigation: Inventory → Deliveries
1. Click "+ Add Delivery"
2. Enter client name
3. Add products with quantities
4. Upload delivery proof (optional)
5. Submit
✅ Stock automatically decreases
```

#### Creating Bookings
```
Navigation: History → Bookings
1. Click "+ Create Booking"
2. Enter client and location
3. Add items with quantities and prices
4. Enter amount and payment
5. Submit
```

#### Recording Payments
```
Navigation: History → Payments
1. Click "+ Record Payment"
2. Select client
3. Enter amount and method
4. Upload receipt (optional)
5. Submit
```

#### Direct Sales
```
Navigation: History → Direct Sales
1. Click "+ Add Sale"
2. Enter client name
3. Add items with quantities and prices
4. Enter payment details
5. Submit
```

---

## 🎯 Features by Section

### Dashboard
- Total stock value
- Today's IN/OUT summary
- Recent transactions
- Quick stats

### Inventory Section
- **GRN (Receiving)**: Record incoming materials
- **Deliveries**: Record outgoing materials
- **Stock Summary**: Current inventory levels
- **Daily Breakdown**: Today's transactions
- **History**: Complete transaction log

### Sales Section
- **Bookings**: Customer orders
- **Direct Sales**: Direct customer sales
- **Payments**: Payment tracking
- **Client Ledger**: Client transaction history
- **Pending Bills**: Unpaid bills tracking
- **Unpaid/Paid Transactions**: Receivables overview

### Directory (Admin Only)
- **Material Brands**: Manage materials
- **Clients**: Manage client information

### System
- **Settings**: User management, permissions, company settings
- **Import & Export**: Bulk data operations
- **Logout**: Secure logout

---

## 👤 User Roles & Permissions

### Admin
- Full access to all features
- User management
- Settings configuration
- Import/Export
- Directory management

### User (Customizable)
- `can_view_stock`: Access to Stock Summary
- `can_view_daily`: Access to Daily Breakdown
- `can_view_history`: Access to transaction history
- `can_import_export`: Access to data import/export
- `can_manage_directory`: Access to manage clients/materials

---

## 🗂️ File Structure

```
ahmed_cement_final/
├── main.py                 # Main application (2500+ lines)
├── models.py              # Database models
├── requirements.txt       # Python dependencies
├── README.md             # This file
│
├── instance/             # Database folder
│   └── ahmed_cement.db  # SQLite database
│
├── static/               # Static files
│   └── uploads/         # Photo uploads
│
├── templates/            # HTML templates (27 files)
│   ├── layout.html      # Base layout (dark theme)
│   ├── index.html       # Dashboard
│   ├── login.html       # Login page
│   ├── grn.html         # GRN management
│   ├── deliveries.html  # Deliveries
│   ├── materials.html   # Material management
│   ├── clients.html     # Client management
│   ├── bookings.html    # Bookings
│   ├── direct_sales.html # Direct sales
│   ├── payments.html    # Payments
│   ├── tracking.html    # Transaction history
│   ├── stock_summary.html # Stock overview
│   ├── daily_transactions.html # Daily breakdown
│   ├── client_ledger.html # Client ledger
│   ├── pending_bills.html # Pending bills
│   ├── settings.html    # System settings
│   └── [22 more templates]
│
├── blueprints/           # Modular routes (optional)
│   ├── admin.py
│   ├── data_lab.py
│   ├── import_export.py
│   └── inventory.py
│
└── utils/                # Utility functions
    └── module_loader.py
```

---

## 🔧 Advanced Configuration

### Database
- SQLite database located at `instance/ahmed_cement.db`
- Automatic schema migrations on startup
- Backup database through Settings page

### Photo Uploads
- Max file size: 16MB
- Location: `static/uploads/`
- Supported formats: JPG, PNG, PDF
- Naming: Timestamp + original filename

### Bill Numbering
- Auto-generated format: #1000, #1001, #1002...
- Counter stored in `BillCounter` table
- Can be customized through database

---

## 📊 Database Schema

### Main Tables
- `user` - User accounts and permissions
- `client` - Client master with auto codes
- `material` - Material master with auto codes
- `entry` - Complete IN/OUT transaction log
- `grn` + `grn_item` - Goods receipt notes
- `booking` + `booking_item` - Customer bookings
- `delivery` + `delivery_item` - Deliveries
- `direct_sale` + `direct_sale_item` - Direct sales
- `payment` - Payment records
- `invoice` - Invoice management
- `pending_bill` - Unpaid bills tracking
- `bill_counter` - Auto bill numbering
- `settings` - System configuration

---

## 🐛 Troubleshooting

### App won't start?
```bash
# Check Python version
python --version  # Should be 3.10+

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall

# Delete database and restart (⚠️ will lose data)
rm instance/ahmed_cement.db
python main.py
```

### Can't login?
- Use default: admin / admin123
- Clear browser cache
- Check if `instance/ahmed_cement.db` exists

### Photos not uploading?
- Check file size (max 16MB)
- Ensure `static/uploads/` folder exists
- Check file permissions

### Stock not updating?
- Ensure material exists in Material Brands
- Check transaction was successful (flash message)
- View History to verify entry was created

---

## 🔒 Security Best Practices

1. **Change default password** immediately
2. **Regular backups** (Settings → Backup Database)
3. **Limit admin access** to trusted users only
4. **Use strong passwords** for all accounts
5. **Keep Python and dependencies updated**
6. **Restrict file upload types** if needed
7. **Enable HTTPS** in production

---

## 📈 What's New in v2.0

### Merged Features
✅ Combined best features from both original apps  
✅ Enhanced dark theme UI from 9000v5  
✅ Added GRN functionality from pyanywhere  
✅ Added Deliveries functionality from pyanywhere  
✅ Unified database schema  
✅ Consistent navigation and UX  

### UI Improvements
✅ Professional dark theme (dark blue/gold)  
✅ Collapsible sidebar with scrolling  
✅ Responsive mobile design  
✅ Modal-based forms  
✅ Loading indicators  
✅ Better icons and typography  

### New Features
✅ Auto-generated client codes (tmpc-000001)  
✅ Auto-generated material codes (tmpm-00001)  
✅ Enhanced permissions system  
✅ Material total tracking  
✅ Comprehensive entry logging  
✅ Settings table for configuration  

---

## 🎓 Learning Resources

### For Beginners
1. Start with Dashboard to understand overview
2. Add 2-3 test materials
3. Add 1-2 test clients
4. Create a test GRN
5. Create a test delivery
6. View history to see transaction log
7. Delete test data before production use

### For Administrators
1. Review user permissions
2. Configure company settings
3. Set up regular backup schedule
4. Train users on specific sections
5. Monitor transaction logs

---

## 📞 Support

### Common Questions

**Q: How do I backup my data?**  
A: Settings → Backup Database → Download .db file

**Q: Can I change the bill number format?**  
A: Currently #1000 format. Can be customized in database.

**Q: How do I add more users?**  
A: Settings → Add User → Set permissions

**Q: Can I export data to Excel?**  
A: Yes, use Import & Export section (admin only)

**Q: Mobile app available?**  
A: Mobile-responsive web app, access via browser

---

## 📝 Version History

### v2.0 (Current) - February 2026
- Merged both applications
- Enhanced dark UI
- Added GRN and Deliveries
- Auto-generated codes
- Comprehensive documentation

### v1.x (Original Apps)
- App 1: pyanywhere (CRM features)
- App 2: 9000v5 (Advanced UI and features)

---

## 🎯 Future Enhancements (Planned)

- [ ] Advanced reporting with charts
- [ ] Email notifications
- [ ] SMS integration
- [ ] Barcode scanning
- [ ] Multi-warehouse support
- [ ] API endpoints
- [ ] Mobile native app
- [ ] Multi-language support

---

## ⚖️ License

Proprietary - For authorized use only

---

## 🙏 Acknowledgments

This integrated system combines:
- Comprehensive CRM features from pyanywhere app
- Professional dark UI from 9000v5 app
- Enhanced functionality and bug fixes
- Unified user experience

---

**Made with ❤️ for Ahmed Cement**

*Professional Inventory Management System*  
*Version 2.0 - February 2026*
