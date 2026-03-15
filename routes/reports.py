from flask import Blueprint, render_template, request, jsonify, send_file
from flask_login import login_required, current_user
from models.database import db, Employee, Attendance, User
from datetime import datetime, timedelta, date as dt_date
from utils.logger import app_logger
import io
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')


@reports_bp.route('/')
@login_required
def index():
    """Reports dashboard - रिपोर्ट डैशबोर्ड"""
    try:
        today = dt_date.today()

        # Today's stats
        today_attendance = Attendance.query.filter(
            Attendance.date == today
        ).count()

        total_employees = Employee.query.filter_by(is_active=True).count()

        # This month stats
        month_start = today.replace(day=1)
        month_attendance = Attendance.query.filter(
            Attendance.date >= month_start
        ).count()

        stats = {
            'today_present': today_attendance,
            'total_employees': total_employees,
            'today_absent': total_employees - today_attendance,
            'month_total': month_attendance
        }

        return render_template('reports.html', stats=stats)
    except Exception as e:
        app_logger.error(f"Error loading reports page: {e}", exc_info=True)
        return render_template('error.html', error_message=str(e)), 500


@reports_bp.route('/analytics')
@login_required
def analytics():
    """Advanced analytics page (placeholder)"""
    return render_template('reports.html')


@reports_bp.route('/audit-logs')
@login_required
def audit_logs():
    """Audit logs page"""
    from models.database import AuditLog
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(100).all()
    return render_template('reports.html', audit_logs=logs)


@reports_bp.route('/generate', methods=['POST'])
@login_required
def generate_report():
    """Generate and download attendance report"""
    try:
        data = request.get_json()
        report_type = data.get('format', 'excel')
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')

        start = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end = datetime.strptime(end_date_str, '%Y-%m-%d').date()

        # Reuse the Excel download logic
        return download_daily_excel(start_date_str)

    except Exception as e:
        app_logger.error(f"Error generating report: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@reports_bp.route('/daily', methods=['GET'])
@login_required
def daily_report():
    """Generate daily attendance report - दैनिक रिपोर्ट"""
    try:
        date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        # Get attendance records
        attendance_records = db.session.query(Attendance, Employee).join(
            Employee, Attendance.employee_id == Employee.id
        ).filter(Attendance.date == report_date).all()

        # Get all employees
        all_employees = Employee.query.filter_by(is_active=True).all()

        # Build report data
        report_data = []
        present_ids = [a.employee_id for a, e in attendance_records]

        for emp in all_employees:
            attendance = next((a for a, e in attendance_records if a.employee_id == emp.id), None)

            report_data.append({
                'army_id': emp.army_id,
                'name': emp.full_name,
                'rank': emp.rank or 'N/A',
                'unit': emp.unit or 'N/A',
                'check_in': attendance.check_in_time.strftime(
                    '%I:%M %p') if attendance and attendance.check_in_time else 'अनुपस्थित / Absent',
                'check_out': attendance.check_out_time.strftime(
                    '%I:%M %p') if attendance and attendance.check_out_time else '-',
                'status': 'उपस्थित / Present' if attendance else 'अनुपस्थित / Absent',
                'status_class': 'success' if attendance else 'danger'
            })

        total_employees = len(all_employees)
        present_count = len([r for r in report_data if 'Present' in r['status']])
        absent_count = total_employees - present_count
        attendance_percentage = (present_count / total_employees * 100) if total_employees > 0 else 0

        stats = {
            'total': total_employees,
            'present': present_count,
            'absent': absent_count,
            'percentage': round(attendance_percentage, 1)
        }

        return render_template('reports.html',
                               report_data=report_data,
                               report_date=report_date,
                               stats=stats)

    except Exception as e:
        app_logger.error(f"Error generating daily report: {e}", exc_info=True)
        return render_template('error.html', error_message=str(e)), 500


@reports_bp.route('/monthly')
@login_required
def monthly_report():
    """Generate monthly attendance report - मासिक रिपोर्ट"""
    try:
        month = request.args.get('month', datetime.now().strftime('%Y-%m'))
        year, month_num = map(int, month.split('-'))

        # Get attendance for the month
        start_date = datetime(year, month_num, 1)
        if month_num == 12:
            end_date = datetime(year + 1, 1, 1)
        else:
            end_date = datetime(year, month_num + 1, 1)

        attendance_records = Attendance.query.filter(
            Attendance.date >= start_date.date(),
            Attendance.date < end_date.date()
        ).all()

        # Get all employees
        employees = Employee.query.filter_by(is_active=True).all()

        # Calculate attendance for each employee
        report_data = []
        working_days = (end_date - start_date).days

        for emp in employees:
            emp_attendance = [a for a in attendance_records if a.employee_id == emp.id]
            present_days = len(set([a.date for a in emp_attendance]))
            percentage = round(present_days / working_days * 100, 1) if working_days > 0 else 0

            report_data.append({
                'army_id': emp.army_id,
                'name': emp.full_name,
                'rank': emp.rank or 'N/A',
                'unit': emp.unit or 'N/A',
                'present_days': present_days,
                'working_days': working_days,
                'percentage': percentage,
                'status_class': 'success' if percentage >= 90 else 'warning' if percentage >= 75 else 'danger'
            })

        # Sort by percentage
        report_data.sort(key=lambda x: x['percentage'], reverse=True)

        return render_template('reports.html',
                               report_data=report_data,
                               month=month,
                               month_name=start_date.strftime('%B %Y'))

    except Exception as e:
        app_logger.error(f"Error generating monthly report: {e}", exc_info=True)
        return render_template('error.html', error_message=str(e)), 500


@reports_bp.route('/employee/<army_id>')
@login_required
def employee_report(army_id):
    """Individual employee report - व्यक्तिगत रिपोर्ट"""
    try:
        employee = Employee.query.filter_by(army_id=army_id).first_or_404()

        # Get date range
        start_date_str = request.args.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
        end_date_str = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))

        start = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end = datetime.strptime(end_date_str, '%Y-%m-%d').date()

        # Get attendance records
        attendance_records = Attendance.query.filter(
            Attendance.employee_id == employee.id,
            Attendance.date >= start,
            Attendance.date <= end
        ).order_by(Attendance.date.desc()).all()

        # Calculate statistics
        present_days = len(set([a.date for a in attendance_records]))
        total_days = (end - start).days + 1
        percentage = round(present_days / total_days * 100, 1) if total_days > 0 else 0

        stats = {
            'present_days': present_days,
            'total_days': total_days,
            'percentage': percentage,
            'on_time': sum(1 for a in attendance_records if a.status == 'present'),
            'late': sum(1 for a in attendance_records if a.status == 'late'),
            'half_day': sum(1 for a in attendance_records if a.status == 'half_day')
        }

        return render_template('reports.html',
                               employee=employee,
                               attendance_records=attendance_records,
                               stats=stats,
                               start_date=start,
                               end_date=end)

    except Exception as e:
        app_logger.error(f"Error generating employee report: {e}", exc_info=True)
        return render_template('error.html', error_message=str(e)), 500


@reports_bp.route('/download/excel/daily/<date_str>')
@login_required
def download_daily_excel(date_str):
    """Download daily report as Excel"""
    try:
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        # Create workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = f"Daily Report"

        # Title
        ws.merge_cells('A1:G1')
        title_cell = ws['A1']
        title_cell.value = f'Daily Attendance Report - {report_date.strftime("%d %B %Y")}'
        title_cell.font = Font(size=16, bold=True)
        title_cell.alignment = Alignment(horizontal='center')

        # Header style
        header_fill = PatternFill(start_color="1F4788", end_color="1F4788", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True, size=12)
        header_alignment = Alignment(horizontal="center", vertical="center")

        # Headers
        headers = ['Army ID', 'Name', 'Rank', 'Unit', 'Check In', 'Check Out', 'Status']
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=3, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = header_alignment

        # Get data
        attendance_records = db.session.query(Attendance, Employee).join(
            Employee, Attendance.employee_id == Employee.id
        ).filter(Attendance.date == report_date).all()

        # Add data
        for row, (att, emp) in enumerate(attendance_records, 4):
            ws.cell(row=row, column=1, value=emp.army_id)
            ws.cell(row=row, column=2, value=emp.full_name)
            ws.cell(row=row, column=3, value=emp.rank or 'N/A')
            ws.cell(row=row, column=4, value=emp.unit or 'N/A')
            ws.cell(row=row, column=5, value=att.check_in_time.strftime('%I:%M %p'))
            ws.cell(row=row, column=6, value=att.check_out_time.strftime('%I:%M %p') if att.check_out_time else '-')
            ws.cell(row=row, column=7, value='Present')

        # Adjust column widths
        for col in range(1, 8):
            ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 15

        # Save to buffer
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        return send_file(
            buffer,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'daily_report_{date_str}.xlsx'
        )

    except Exception as e:
        app_logger.error(f"Error generating Excel: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
