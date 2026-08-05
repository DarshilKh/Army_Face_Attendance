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
    """Reports dashboard"""
    try:
        today = dt_date.today()

        today_attendance = Attendance.query.filter(
            Attendance.date == today
        ).count()

        total_employees = Employee.query.filter_by(is_active=True).count()

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


# ── Fix 1: generate_report() now branches on format instead of always
#    calling download_daily_excel() regardless of what the user selected.
# ── Fix 2: download_daily_pdf() is now implemented (was imported but
#    never written — reportlab was a dead import before this change).
# ─────────────────────────────────────────────────────────────────────

@reports_bp.route('/generate', methods=['POST'])
@login_required
def generate_report():
    """
    Generate and download attendance report.

    Reads 'format' from the JSON body ('excel' or 'pdf') and routes to
    the correct download helper.  Previously this always called
    download_daily_excel() no matter which format was selected.
    """
    try:
        data           = request.get_json()
        report_type    = data.get('format', 'excel')   # 'excel' or 'pdf'
        start_date_str = data.get('start_date')

        # ── Branching fix ─────────────────────────────────────────────────
        if report_type == 'pdf':
            return download_daily_pdf(start_date_str)
        else:
            return download_daily_excel(start_date_str)
        # ─────────────────────────────────────────────────────────────────

    except Exception as e:
        app_logger.error(f"Error generating report: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@reports_bp.route('/daily', methods=['GET'])
@login_required
def daily_report():
    """Generate daily attendance report"""
    try:
        date_str    = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        attendance_records = db.session.query(Attendance, Employee).join(
            Employee, Attendance.employee_id == Employee.id
        ).filter(Attendance.date == report_date).all()

        all_employees = Employee.query.filter_by(is_active=True).all()

        report_data = []
        for emp in all_employees:
            attendance = next(
                (a for a, e in attendance_records if a.employee_id == emp.id), None
            )
            report_data.append({
                'army_id':      emp.army_id,
                'name':         emp.full_name,
                'rank':         emp.rank or 'N/A',
                'unit':         emp.unit or 'N/A',
                'check_in':     attendance.check_in_time.strftime('%I:%M %p')
                                if attendance and attendance.check_in_time
                                else 'Absent',
                'check_out':    attendance.check_out_time.strftime('%I:%M %p')
                                if attendance and attendance.check_out_time
                                else '-',
                'status':       'Present' if attendance else 'Absent',
                'status_class': 'success' if attendance else 'danger'
            })

        total_employees       = len(all_employees)
        present_count         = len([r for r in report_data if r['status'] == 'Present'])
        absent_count          = total_employees - present_count
        attendance_percentage = (present_count / total_employees * 100) if total_employees > 0 else 0

        stats = {
            'total':      total_employees,
            'present':    present_count,
            'absent':     absent_count,
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
    """Generate monthly attendance report"""
    try:
        month            = request.args.get('month', datetime.now().strftime('%Y-%m'))
        year, month_num  = map(int, month.split('-'))

        start_date = datetime(year, month_num, 1)
        end_date   = datetime(year + 1, 1, 1) if month_num == 12 else datetime(year, month_num + 1, 1)

        attendance_records = Attendance.query.filter(
            Attendance.date >= start_date.date(),
            Attendance.date <  end_date.date()
        ).all()

        employees    = Employee.query.filter_by(is_active=True).all()
        working_days = (end_date - start_date).days
        report_data  = []

        for emp in employees:
            emp_attendance = [a for a in attendance_records if a.employee_id == emp.id]
            present_days   = len(set(a.date for a in emp_attendance))
            percentage     = round(present_days / working_days * 100, 1) if working_days > 0 else 0

            report_data.append({
                'army_id':      emp.army_id,
                'name':         emp.full_name,
                'rank':         emp.rank or 'N/A',
                'unit':         emp.unit or 'N/A',
                'present_days': present_days,
                'working_days': working_days,
                'percentage':   percentage,
                'status_class': 'success' if percentage >= 90 else 'warning' if percentage >= 75 else 'danger'
            })

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
    """Individual employee report"""
    try:
        employee = Employee.query.filter_by(army_id=army_id).first_or_404()

        start_date_str = request.args.get(
            'start_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        )
        end_date_str = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))

        start = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end   = datetime.strptime(end_date_str,   '%Y-%m-%d').date()

        attendance_records = Attendance.query.filter(
            Attendance.employee_id == employee.id,
            Attendance.date >= start,
            Attendance.date <= end
        ).order_by(Attendance.date.desc()).all()

        present_days = len(set(a.date for a in attendance_records))
        total_days   = (end - start).days + 1
        percentage   = round(present_days / total_days * 100, 1) if total_days > 0 else 0

        stats = {
            'present_days': present_days,
            'total_days':   total_days,
            'percentage':   percentage,
            'on_time':      sum(1 for a in attendance_records if a.status == 'present'),
            'late':         sum(1 for a in attendance_records if a.status == 'late'),
            'half_day':     sum(1 for a in attendance_records if a.status == 'half_day')
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

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Daily Report"

        ws.merge_cells('A1:G1')
        title_cell           = ws['A1']
        title_cell.value     = f'Daily Attendance Report - {report_date.strftime("%d %B %Y")}'
        title_cell.font      = Font(size=16, bold=True)
        title_cell.alignment = Alignment(horizontal='center')

        header_fill      = PatternFill(start_color="1F4788", end_color="1F4788", fill_type="solid")
        header_font      = Font(color="FFFFFF", bold=True, size=12)
        header_alignment = Alignment(horizontal="center", vertical="center")

        headers = ['Army ID', 'Name', 'Rank', 'Unit', 'Check In', 'Check Out', 'Status']
        for col, header in enumerate(headers, 1):
            cell           = ws.cell(row=3, column=col, value=header)
            cell.fill      = header_fill
            cell.font      = header_font
            cell.alignment = header_alignment

        attendance_records = db.session.query(Attendance, Employee).join(
            Employee, Attendance.employee_id == Employee.id
        ).filter(Attendance.date == report_date).all()

        for row, (att, emp) in enumerate(attendance_records, 4):
            ws.cell(row=row, column=1, value=emp.army_id)
            ws.cell(row=row, column=2, value=emp.full_name)
            ws.cell(row=row, column=3, value=emp.rank or 'N/A')
            ws.cell(row=row, column=4, value=emp.unit or 'N/A')
            ws.cell(row=row, column=5, value=att.check_in_time.strftime('%I:%M %p'))
            ws.cell(row=row, column=6,
                    value=att.check_out_time.strftime('%I:%M %p') if att.check_out_time else '-')
            ws.cell(row=row, column=7, value='Present')

        for col in range(1, 8):
            ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 15

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


# ── Fix 2: PDF generation — reportlab was fully imported at the top of the
#    file in the original code but this function was never written, making
#    the import dead code and PDF downloads impossible.
# ─────────────────────────────────────────────────────────────────────────────
@reports_bp.route('/download/pdf/daily/<date_str>')
@login_required
def download_daily_pdf(date_str):
    """
    Download daily report as PDF.

    This function was missing entirely from the original file despite
    reportlab being imported.  generate_report() now calls this when
    format == 'pdf'.
    """
    try:
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        attendance_records = db.session.query(Attendance, Employee).join(
            Employee, Attendance.employee_id == Employee.id
        ).filter(Attendance.date == report_date).all()

        buffer = io.BytesIO()
        doc    = SimpleDocTemplate(buffer, pagesize=landscape(A4))
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'TitleStyle',
            parent=styles['Heading1'],
            alignment=TA_CENTER,
            fontSize=16
        )

        elements = []

        # Title
        elements.append(
            Paragraph(
                f'Daily Attendance Report - {report_date.strftime("%d %B %Y")}',
                title_style
            )
        )
        elements.append(Spacer(1, 20))

        # Table data
        table_data = [
            ['Army ID', 'Name', 'Rank', 'Unit', 'Check In', 'Check Out', 'Status']
        ]

        for att, emp in attendance_records:
            table_data.append([
                emp.army_id,
                emp.full_name,
                emp.rank or 'N/A',
                emp.unit or 'N/A',
                att.check_in_time.strftime('%I:%M %p'),
                att.check_out_time.strftime('%I:%M %p') if att.check_out_time else '-',
                'Present'
            ])

        # Table styling
        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND',     (0, 0), (-1, 0),  colors.HexColor('#1F4788')),
            ('TEXTCOLOR',      (0, 0), (-1, 0),  colors.white),
            ('FONTNAME',       (0, 0), (-1, 0),  'Helvetica-Bold'),
            ('ALIGN',          (0, 0), (-1, -1), 'CENTER'),
            ('GRID',           (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F3F4F6')]),
        ]))

        elements.append(table)

        doc.build(elements)
        buffer.seek(0)

        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'daily_report_{date_str}.pdf'
        )

    except Exception as e:
        app_logger.error(f"Error generating PDF: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500