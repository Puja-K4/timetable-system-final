from flask import Flask, render_template, request, redirect, session, flash, url_for, jsonify
from firebase_config import db
import pandas as pd
import os
from functools import wraps
from datetime import timedelta
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")
app.permanent_session_lifetime = timedelta(minutes=30)

ALLOWED_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
ALLOWED_TYPES = ["Theory", "Practical"]
ALLOWED_TERMS = ["Term I", "Term II"]


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin'):
            flash("Please login first.", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def normalize_text(value):
    return " ".join(str(value).strip().split())


def make_doc_id(*parts):
    cleaned = []
    for part in parts:
        value = normalize_text(part).lower()
        value = value.replace(" ", "-").replace("/", "-")
        cleaned.append(value)
    return "__".join(cleaned)


def faculty_exists(name, department):
    doc_id = make_doc_id(department, name)
    return db.collection("faculty").document(doc_id).get().exists


def safe_list_from_collection(collection_name, field_name, department=None):
    query = db.collection(collection_name)
    if department:
        query = query.where("department", "==", department)

    values = []
    for doc in query.stream():
        data = doc.to_dict()
        if data.get(field_name):
            values.append(data[field_name])

    return sorted(set(values))


def get_allowed_subjects(department, class_name, term):
    class_name = normalize_text(class_name)
    term = normalize_text(term)

    if not class_name or not term:
        return []

    docs = db.collection("class_subjects") \
        .where("department", "==", department) \
        .where("class", "==", class_name) \
        .where("term", "==", term) \
        .stream()

    subjects = []
    for doc in docs:
        data = doc.to_dict()
        subject_name = normalize_text(data.get("subject", ""))
        if subject_name:
            subjects.append(subject_name)

    return sorted(set(subjects))


@app.route('/')
def home():
    docs = db.collection("timetable").stream()
    data = [d.to_dict() for d in docs]

    departments = sorted(set([d.get('department') for d in data if d.get('department')]))
    years = sorted(set([d.get('year') for d in data if d.get('year')]))
    terms = sorted(set([d.get('term') for d in data if d.get('term')]))
    classes = sorted(set([d.get('class') for d in data if d.get('class')]))

    return render_template(
        "home.html",
        departments=departments,
        years=years,
        terms=terms,
        classes=classes
    )


@app.route('/faculty-select')
def faculty_select():
    docs = db.collection("timetable").stream()
    data = [d.to_dict() for d in docs]

    departments = sorted(set([d.get('department') for d in data if d.get('department')]))
    years = sorted(set([d.get('year') for d in data if d.get('year')]))
    terms = sorted(set([d.get('term') for d in data if d.get('term')]))
    faculty = sorted(set([d.get('faculty') for d in data if d.get('faculty')]))

    return render_template(
        "faculty_select.html",
        departments=departments,
        years=years,
        terms=terms,
        faculty=faculty
    )


@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = normalize_text(request.form.get('email', ''))
        password = request.form.get('password', '').strip()
        department = normalize_text(request.form.get('department', ''))

        if not email or not password or not department:
            flash("All fields are required.", "error")
            return redirect(url_for('login'))

        admins = db.collection("admins") \
            .where("email", "==", email) \
            .where("department", "==", department) \
            .stream()

        for admin in admins:
            data = admin.to_dict()
            stored_password = data.get('password', '')

            if stored_password and check_password_hash(stored_password, password):
                session.clear()
                session.permanent = True
                session['admin'] = True
                session['department'] = department
                return redirect(url_for('select_session'))

        flash("Invalid email, password, or department.", "error")
        return redirect(url_for('login'))

    depts = [d.to_dict().get('name') for d in db.collection("departments").stream() if d.to_dict().get('name')]
    depts = sorted(set(depts))
    return render_template("login.html", departments=depts)


@app.route('/admin/select-session', methods=['GET', 'POST'])
@admin_required
def select_session():
    if request.method == 'POST':
        year = normalize_text(request.form.get('year', ''))
        term = normalize_text(request.form.get('term', ''))

        if not year or not term:
            flash("Year and term are required.", "error")
            return redirect(url_for('select_session'))

        session['year'] = year
        session['term'] = term
        return redirect(url_for('dashboard'))

    sessions = list(db.collection("academic_sessions").stream())

    years = []
    active_year = None

    for s in sessions:
        data = s.to_dict()
        if data.get('year'):
            years.append(data['year'])
        if data.get('active') is True:
            active_year = data.get('year')

    years = sorted(set(years))

    return render_template(
        "select_session.html",
        years=years,
        active_year=active_year
    )


@app.route('/admin/dashboard')
@admin_required
def dashboard():
    if not session.get('year') or not session.get('term'):
        return redirect(url_for('select_session'))

    return render_template("dashboard.html")


@app.route('/admin/faculty', methods=['GET', 'POST'])
@admin_required
def faculty():
    dept = session.get('department')

    if request.method == 'POST':
        name = normalize_text(request.form.get('name', ''))

        if not name:
            flash("Faculty name is required.", "error")
            return redirect(url_for('faculty'))

        doc_id = make_doc_id(dept, name)
        doc_ref = db.collection("faculty").document(doc_id)

        if doc_ref.get().exists:
            flash("Faculty already exists in this department.", "error")
            return redirect(url_for('faculty'))

        doc_ref.set({
            "name": name,
            "department": dept
        })

        flash("Faculty added successfully.", "success")
        return redirect(url_for('faculty'))

    docs = db.collection("faculty").where("department", "==", dept).stream()

    data = []
    for d in docs:
        item = d.to_dict()
        item['id'] = d.id
        data.append(item)

    data.sort(key=lambda x: x.get("name", ""))
    return render_template("faculty.html", data=data)


@app.route('/admin/upload-master', methods=['GET', 'POST'])
@admin_required
def upload_master():
    dept = session.get('department')

    if request.method == 'POST':
        if 'file' not in request.files:
            flash("No file selected.", "error")
            return redirect(url_for('upload_master'))

        file = request.files['file']

        if not file or file.filename == '':
            flash("Please choose an Excel file.", "error")
            return redirect(url_for('upload_master'))

        try:
            excel_data = pd.ExcelFile(file)

            faculty_df = pd.read_excel(excel_data, sheet_name="Faculty")
            subjects_df = pd.read_excel(excel_data, sheet_name="Subjects")
            classes_df = pd.read_excel(excel_data, sheet_name="Classes")
            timeslots_df = pd.read_excel(excel_data, sheet_name="TimeSlots")
            rooms_df = pd.read_excel(excel_data, sheet_name="Rooms")
            class_subjects_df = pd.read_excel(excel_data, sheet_name="ClassSubjects")
        except Exception as e:
            flash(f"Error reading Excel file: {str(e)}", "error")
            return redirect(url_for('upload_master'))

        for _, row in faculty_df.iterrows():
            name = normalize_text(row.get("name", ""))
            if not name:
                continue

            doc_id = make_doc_id(dept, name)
            db.collection("faculty").document(doc_id).set({
                "name": name,
                "department": dept
            })

        for _, row in subjects_df.iterrows():
            subject_name = normalize_text(row.get("subject", ""))
            if not subject_name:
                continue

            doc_id = make_doc_id(dept, subject_name)
            db.collection("subjects").document(doc_id).set({
                "name": subject_name,
                "department": dept
            })

        for _, row in classes_df.iterrows():
            class_name = normalize_text(row.get("class", ""))
            if not class_name:
                continue

            doc_id = make_doc_id(dept, class_name)
            db.collection("classes").document(doc_id).set({
                "name": class_name,
                "department": dept
            })

        for _, row in timeslots_df.iterrows():
            slot = normalize_text(row.get("slot", ""))
            if not slot:
                continue

            doc_id = make_doc_id(slot)
            db.collection("timeslots").document(doc_id).set({
                "slot": slot
            })

        for _, row in rooms_df.iterrows():
            room = normalize_text(row.get("room", ""))
            if not room:
                continue

            doc_id = make_doc_id(room)
            db.collection("rooms").document(doc_id).set({
                "room": room
            })

        for _, row in class_subjects_df.iterrows():
            class_name = normalize_text(row.get("class", ""))
            term = normalize_text(row.get("term", ""))
            subject_name = normalize_text(row.get("subject", ""))

            if not class_name or not term or not subject_name:
                continue

            if term not in ALLOWED_TERMS:
                continue

            doc_id = make_doc_id(dept, class_name, term, subject_name)
            db.collection("class_subjects").document(doc_id).set({
                "department": dept,
                "class": class_name,
                "term": term,
                "subject": subject_name
            })

        flash("Master data uploaded successfully.", "success")
        return redirect(url_for('upload_master'))

    return render_template("upload_master.html")


@app.route('/admin/class-subjects', methods=['GET', 'POST'])
@admin_required
def class_subjects():
    dept = session.get('department')

    classes = safe_list_from_collection("classes", "name", dept)
    subjects = safe_list_from_collection("subjects", "name", dept)

    if request.method == 'POST':
        class_name = normalize_text(request.form.get('class', ''))
        term = normalize_text(request.form.get('term', ''))
        subject = normalize_text(request.form.get('subject', ''))

        if not class_name or not term or not subject:
            flash("Class, term, and subject are required.", "error")
            return redirect(url_for('class_subjects'))

        if class_name not in classes:
            flash("Invalid class selected.", "error")
            return redirect(url_for('class_subjects'))

        if subject not in subjects:
            flash("Invalid subject selected.", "error")
            return redirect(url_for('class_subjects'))

        if term not in ALLOWED_TERMS:
            flash("Invalid term selected.", "error")
            return redirect(url_for('class_subjects'))

        doc_id = make_doc_id(dept, class_name, term, subject)
        doc_ref = db.collection("class_subjects").document(doc_id)

        if doc_ref.get().exists:
            flash("This subject is already assigned to this class and term.", "error")
            return redirect(url_for('class_subjects'))

        doc_ref.set({
            "department": dept,
            "class": class_name,
            "term": term,
            "subject": subject
        })

        flash("Subject assigned to class and term successfully.", "success")
        return redirect(url_for('class_subjects'))

    docs = db.collection("class_subjects").where("department", "==", dept).stream()

    data = []
    for d in docs:
        item = d.to_dict()
        item["id"] = d.id
        data.append(item)

    data.sort(key=lambda x: (x.get("class", ""), x.get("term", ""), x.get("subject", "")))

    return render_template(
        "class_subjects.html",
        classes=classes,
        subjects=subjects,
        terms=ALLOWED_TERMS,
        data=data
    )


@app.route('/admin/delete-class-subject/<id>')
@admin_required
def delete_class_subject(id):
    doc = db.collection("class_subjects").document(id).get()

    if not doc.exists:
        flash("Mapping not found.", "error")
        return redirect(url_for('class_subjects'))

    db.collection("class_subjects").document(id).delete()
    flash("Mapping deleted successfully.", "success")
    return redirect(url_for('class_subjects'))


@app.route('/admin/upload-faculty', methods=['POST'])
@admin_required
def upload_faculty():
    if 'file' not in request.files:
        flash("No file selected.", "error")
        return redirect(url_for('faculty'))

    file = request.files['file']

    if not file or file.filename == '':
        flash("Please choose an Excel file.", "error")
        return redirect(url_for('faculty'))

    dept = session.get('department')

    try:
        df = pd.read_excel(file)
    except Exception:
        flash("Invalid Excel file.", "error")
        return redirect(url_for('faculty'))

    if 'name' not in df.columns:
        flash("Excel file must contain a 'name' column.", "error")
        return redirect(url_for('faculty'))

    added_count = 0
    skipped_count = 0
    seen_in_file = set()

    for _, row in df.iterrows():
        name = normalize_text(row.get('name', ''))

        if not name:
            skipped_count += 1
            continue

        key = name.lower()

        if key in seen_in_file:
            skipped_count += 1
            continue

        doc_id = make_doc_id(dept, name)
        doc_ref = db.collection("faculty").document(doc_id)

        if doc_ref.get().exists:
            skipped_count += 1
            continue

        doc_ref.set({
            "name": name,
            "department": dept
        })

        seen_in_file.add(key)
        added_count += 1

    flash(f"Faculty upload complete. Added: {added_count}, Skipped: {skipped_count}", "success")
    return redirect(url_for('faculty'))


@app.route('/admin/delete-faculty/<id>')
@admin_required
def delete_faculty(id):
    faculty_doc = db.collection("faculty").document(id).get()

    if not faculty_doc.exists:
        flash("Faculty not found.", "error")
        return redirect(url_for('faculty'))

    faculty_data = faculty_doc.to_dict()
    faculty_name = faculty_data.get("name", "")
    dept = faculty_data.get("department", "")

    timetable_docs = db.collection("timetable") \
        .where("faculty", "==", faculty_name) \
        .where("department", "==", dept) \
        .stream()

    for _ in timetable_docs:
        flash("Cannot delete faculty because it is already used in timetable.", "error")
        return redirect(url_for('faculty'))

    db.collection("faculty").document(id).delete()
    flash("Faculty deleted successfully.", "success")
    return redirect(url_for('faculty'))


@app.route('/department')
def department():
    dept = request.args.get('department')
    year = request.args.get('year')
    term = request.args.get('term')

    docs = db.collection("timetable") \
        .where("department", "==", dept) \
        .where("year", "==", year) \
        .where("term", "==", term) \
        .stream()

    data = [d.to_dict() for d in docs]

    timetable = {}

    for entry in data:
        key = (entry['time'], entry['class'])

        if key not in timetable:
            timetable[key] = {
                "Monday": [],
                "Tuesday": [],
                "Wednesday": [],
                "Thursday": [],
                "Friday": [],
                "Saturday": []
            }

        day = entry['day']

        if entry['type'] == "Practical":
            text = f"{entry['subject']} ({entry['faculty']}) [{entry.get('batch', '')}] ({entry.get('room', '')})"
        else:
            text = f"{entry['subject']} ({entry['faculty']}) ({entry.get('room', '')})"

        timetable[key][day].append(text)

    return render_template(
        "department.html",
        timetable=timetable,
        dept=dept,
        year=year,
        term=term
    )


@app.route('/admin/departments', methods=['GET', 'POST'])
@admin_required
def departments():
    if request.method == 'POST':
        name = normalize_text(request.form.get('name', ''))

        if not name:
            flash("Department name is required.", "error")
            return redirect(url_for('departments'))

        doc_id = make_doc_id(name)
        doc_ref = db.collection("departments").document(doc_id)

        if doc_ref.get().exists:
            flash("Department already exists.", "error")
            return redirect(url_for('departments'))

        doc_ref.set({"name": name})
        flash("Department added successfully.", "success")
        return redirect(url_for('departments'))

    docs = db.collection("departments").stream()

    data = []
    for d in docs:
        item = d.to_dict()
        item['id'] = d.id
        data.append(item)

    data.sort(key=lambda x: x.get("name", ""))
    return render_template("departments.html", data=data)


@app.route('/admin/classes', methods=['GET', 'POST'])
@admin_required
def classes_admin():
    dept = session.get('department')

    if request.method == 'POST':
        name = normalize_text(request.form.get('name', ''))

        if not name:
            flash("Class name is required.", "error")
            return redirect(url_for('classes_admin'))

        doc_id = make_doc_id(dept, name)
        doc_ref = db.collection("classes").document(doc_id)

        if doc_ref.get().exists:
            flash("Class already exists in this department.", "error")
            return redirect(url_for('classes_admin'))

        doc_ref.set({
            "name": name,
            "department": dept
        })

        flash("Class added successfully.", "success")
        return redirect(url_for('classes_admin'))

    docs = db.collection("classes").where("department", "==", dept).stream()

    data = []
    for d in docs:
        item = d.to_dict()
        item['id'] = d.id
        data.append(item)

    data.sort(key=lambda x: x.get("name", ""))
    return render_template("classes.html", data=data)


@app.route('/admin/delete-class/<id>')
@admin_required
def delete_class(id):
    class_doc = db.collection("classes").document(id).get()

    if not class_doc.exists:
        flash("Class not found.", "error")
        return redirect(url_for('classes_admin'))

    class_data = class_doc.to_dict()
    class_name = class_data.get("name", "")
    dept = class_data.get("department", "")

    timetable_docs = db.collection("timetable") \
        .where("class", "==", class_name) \
        .where("department", "==", dept) \
        .stream()

    for _ in timetable_docs:
        flash("Cannot delete class because it is used in timetable.", "error")
        return redirect(url_for('classes_admin'))

    mapping_docs = db.collection("class_subjects") \
        .where("class", "==", class_name) \
        .where("department", "==", dept) \
        .stream()

    for _ in mapping_docs:
        flash("Cannot delete class because it is used in class-subject mapping.", "error")
        return redirect(url_for('classes_admin'))

    db.collection("classes").document(id).delete()
    flash("Class deleted successfully.", "success")
    return redirect(url_for('classes_admin'))


@app.route('/admin/subjects', methods=['GET', 'POST'])
@admin_required
def subjects_admin():
    dept = session.get('department')

    if request.method == 'POST':
        name = normalize_text(request.form.get('name', ''))

        if not name:
            flash("Subject name is required.", "error")
            return redirect(url_for('subjects_admin'))

        doc_id = make_doc_id(dept, name)
        doc_ref = db.collection("subjects").document(doc_id)

        if doc_ref.get().exists:
            flash("Subject already exists in this department.", "error")
            return redirect(url_for('subjects_admin'))

        doc_ref.set({
            "name": name,
            "department": dept
        })

        flash("Subject added successfully.", "success")
        return redirect(url_for('subjects_admin'))

    docs = db.collection("subjects").where("department", "==", dept).stream()

    data = []
    for d in docs:
        item = d.to_dict()
        item['id'] = d.id
        data.append(item)

    data.sort(key=lambda x: x.get("name", ""))
    return render_template("subjects.html", data=data)


@app.route('/admin/delete-subject/<id>')
@admin_required
def delete_subject(id):
    subject_doc = db.collection("subjects").document(id).get()

    if not subject_doc.exists:
        flash("Subject not found.", "error")
        return redirect(url_for('subjects_admin'))

    subject_data = subject_doc.to_dict()
    subject_name = subject_data.get("name", "")
    dept = subject_data.get("department", "")

    timetable_docs = db.collection("timetable") \
        .where("subject", "==", subject_name) \
        .where("department", "==", dept) \
        .stream()

    for _ in timetable_docs:
        flash("Cannot delete subject because it is used in timetable.", "error")
        return redirect(url_for('subjects_admin'))

    mapping_docs = db.collection("class_subjects") \
        .where("subject", "==", subject_name) \
        .where("department", "==", dept) \
        .stream()

    for _ in mapping_docs:
        flash("Cannot delete subject because it is used in class-subject mapping.", "error")
        return redirect(url_for('subjects_admin'))

    db.collection("subjects").document(id).delete()
    flash("Subject deleted successfully.", "success")
    return redirect(url_for('subjects_admin'))


@app.route('/admin/get-subjects')
@admin_required
def get_subjects_for_class():
    dept = session.get('department')
    class_name = normalize_text(request.args.get('class', ''))
    term = normalize_text(request.args.get('term', ''))

    subjects = get_allowed_subjects(dept, class_name, term)
    return jsonify(subjects)


@app.route('/admin/add-timetable', methods=['GET', 'POST'])
@admin_required
def add_timetable():
    if not session.get('year') or not session.get('term'):
        return redirect(url_for('select_session'))

    dept = session.get('department')
    current_term = session.get('term')

    classes = safe_list_from_collection("classes", "name", dept)
    selected_class = normalize_text(request.form.get('class', ''))
    subjects = get_allowed_subjects(dept, selected_class, current_term) if selected_class else []
    faculty = safe_list_from_collection("faculty", "name", dept)
    timeslots = safe_list_from_collection("timeslots", "slot")
    rooms = safe_list_from_collection("rooms", "room")

    message = ""

    if request.method == 'POST':
        data = {
            "department": dept,
            "year": normalize_text(request.form.get('year', '')),
            "term": normalize_text(request.form.get('term', '')),
            "class": normalize_text(request.form.get('class', '')),
            "day": normalize_text(request.form.get('day', '')),
            "time": normalize_text(request.form.get('time', '')),
            "subject": normalize_text(request.form.get('subject', '')),
            "faculty": normalize_text(request.form.get('faculty', '')),
            "type": normalize_text(request.form.get('type', '')),
            "batch": normalize_text(request.form.get('batch', '')),
            "room": normalize_text(request.form.get('room', ''))
        }

        if data['type'] == "Theory":
            data['batch'] = ''

        required_fields = ['year', 'term', 'class', 'day', 'time', 'subject', 'faculty', 'type', 'room']
        for field in required_fields:
            if not data[field]:
                message = f"❌ {field.capitalize()} is required."
                break

        if not message and data['day'] not in ALLOWED_DAYS:
            message = "❌ Invalid day selected."

        if not message and data['type'] not in ALLOWED_TYPES:
            message = "❌ Invalid lecture type selected."

        if not message and data['time'] not in timeslots:
            message = "❌ Invalid time slot selected."

        if not message and data['class'] not in classes:
            message = "❌ Invalid class selected."

        allowed_subjects = get_allowed_subjects(dept, data['class'], data['term'])
        if not message and data['subject'] not in allowed_subjects:
            message = "❌ Selected subject is not assigned to this class for this term."

        if not message and data['faculty'] not in faculty:
            message = "❌ Invalid faculty selected."

        if not message and data['room'] not in rooms:
            message = "❌ Invalid room selected."

        if not message and data['type'] == "Practical" and not data['batch']:
            message = "❌ Batch is required for practical."

        if not message:
            conflicts = db.collection("timetable") \
                .where("day", "==", data['day']) \
                .where("time", "==", data['time']) \
                .where("department", "==", dept) \
                .where("year", "==", data['year']) \
                .where("term", "==", data['term']) \
                .stream()

            for c in conflicts:
                c = c.to_dict()

                if c['class'] == data['class'] and data['type'] == "Theory":
                    message = "❌ Class already has lecture at this time!"
                    break

                if c['faculty'] == data['faculty']:
                    message = "❌ Faculty already assigned at this time!"
                    break

                if c['room'] == data['room']:
                    message = "❌ Room already occupied!"
                    break

                if data['type'] == "Practical":
                    if c['class'] == data['class'] and c.get('batch', '') == data.get('batch', ''):
                        message = "❌ Same batch already assigned at this time!"
                        break

        if not message:
            db.collection("timetable").add(data)
            flash("Timetable entry added successfully.", "success")
            return redirect(url_for('add_timetable'))

        selected_class = data['class']
        subjects = get_allowed_subjects(dept, selected_class, current_term) if selected_class else []

    docs = db.collection("timetable") \
        .where("department", "==", dept) \
        .where("year", "==", session.get('year')) \
        .where("term", "==", session.get('term')) \
        .stream()

    entries = []
    for d in docs:
        item = d.to_dict()
        item['id'] = d.id
        entries.append(item)

    day_order = {
        "Monday": 1,
        "Tuesday": 2,
        "Wednesday": 3,
        "Thursday": 4,
        "Friday": 5,
        "Saturday": 6
    }

    entries.sort(key=lambda x: (
        x.get('class', ''),
        day_order.get(x.get('day', ''), 99),
        x.get('time', '')
    ))

    return render_template(
        "add_timetable.html",
        dept=dept,
        classes=classes,
        subjects=subjects,
        faculty=faculty,
        timeslots=timeslots,
        rooms=rooms,
        message=message,
        entries=entries
    )


@app.route('/admin/delete-timetable/<id>')
@admin_required
def delete_timetable(id):
    doc = db.collection("timetable").document(id).get()

    if not doc.exists:
        flash("Timetable entry not found.", "error")
        return redirect(url_for('add_timetable'))

    db.collection("timetable").document(id).delete()
    flash("Timetable entry deleted successfully.", "success")
    return redirect(url_for('add_timetable'))


@app.route('/admin/edit-timetable/<id>', methods=['GET', 'POST'])
@admin_required
def edit_timetable(id):
    if not session.get('year') or not session.get('term'):
        return redirect(url_for('select_session'))

    dept = session.get('department')

    doc = db.collection("timetable").document(id).get()
    if not doc.exists:
        flash("Timetable entry not found.", "error")
        return redirect(url_for('add_timetable'))

    entry = doc.to_dict()

    classes = safe_list_from_collection("classes", "name", dept)
    faculty = safe_list_from_collection("faculty", "name", dept)
    timeslots = safe_list_from_collection("timeslots", "slot")
    rooms = safe_list_from_collection("rooms", "room")
    subjects = get_allowed_subjects(dept, entry.get('class', ''), entry.get('term', ''))

    message = ""

    if request.method == 'POST':
        data = {
            "department": dept,
            "year": normalize_text(request.form.get('year', '')),
            "term": normalize_text(request.form.get('term', '')),
            "class": normalize_text(request.form.get('class', '')),
            "day": normalize_text(request.form.get('day', '')),
            "time": normalize_text(request.form.get('time', '')),
            "subject": normalize_text(request.form.get('subject', '')),
            "faculty": normalize_text(request.form.get('faculty', '')),
            "type": normalize_text(request.form.get('type', '')),
            "batch": normalize_text(request.form.get('batch', '')),
            "room": normalize_text(request.form.get('room', ''))
        }

        if data['type'] == "Theory":
            data['batch'] = ''

        subjects = get_allowed_subjects(dept, data['class'], data['term'])

        required_fields = ['year', 'term', 'class', 'day', 'time', 'subject', 'faculty', 'type', 'room']
        for field in required_fields:
            if not data[field]:
                message = f"❌ {field.capitalize()} is required."
                return render_template(
                    "edit_timetable.html",
                    entry=data,
                    classes=classes,
                    subjects=subjects,
                    faculty=faculty,
                    timeslots=timeslots,
                    rooms=rooms,
                    message=message
                )

        if data['day'] not in ALLOWED_DAYS:
            message = "❌ Invalid day selected."
            return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

        if data['type'] not in ALLOWED_TYPES:
            message = "❌ Invalid lecture type selected."
            return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

        if data['time'] not in timeslots:
            message = "❌ Invalid time slot selected."
            return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

        if data['class'] not in classes:
            message = "❌ Invalid class selected."
            return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

        if data['subject'] not in subjects:
            message = "❌ Selected subject is not assigned to this class for this term."
            return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

        if data['faculty'] not in faculty:
            message = "❌ Invalid faculty selected."
            return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

        if data['room'] not in rooms:
            message = "❌ Invalid room selected."
            return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

        if data['type'] == "Practical" and not data['batch']:
            message = "❌ Batch is required for practical."
            return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

        conflicts = db.collection("timetable") \
            .where("day", "==", data['day']) \
            .where("time", "==", data['time']) \
            .where("department", "==", dept) \
            .where("year", "==", data['year']) \
            .where("term", "==", data['term']) \
            .stream()

        for c in conflicts:
            if c.id == id:
                continue

            old = c.to_dict()

            if old['class'] == data['class'] and data['type'] == "Theory":
                message = "❌ Class already has lecture at this time!"
                return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

            if old['faculty'] == data['faculty']:
                message = "❌ Faculty already assigned at this time!"
                return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

            if old['room'] == data['room']:
                message = "❌ Room already occupied!"
                return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

            if data['type'] == "Practical":
                if old['class'] == data['class'] and old.get('batch', '') == data.get('batch', ''):
                    message = "❌ Same batch already assigned at this time!"
                    return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

        db.collection("timetable").document(id).update(data)
        flash("Timetable entry updated successfully.", "success")
        return redirect(url_for('add_timetable'))

    return render_template(
        "edit_timetable.html",
        entry=entry,
        classes=classes,
        subjects=subjects,
        faculty=faculty,
        timeslots=timeslots,
        rooms=rooms,
        message=message
    )


@app.route('/class')
def class_view():
    cls = request.args.get('class')
    dept = request.args.get('department')
    year = request.args.get('year')
    term = request.args.get('term')

    docs = db.collection("timetable") \
        .where("department", "==", dept) \
        .where("year", "==", year) \
        .where("term", "==", term) \
        .where("class", "==", cls) \
        .stream()

    data = [d.to_dict() for d in docs]

    timetable = {}

    for entry in data:
        time = entry['time']

        if time not in timetable:
            timetable[time] = {
                "Monday": [],
                "Tuesday": [],
                "Wednesday": [],
                "Thursday": [],
                "Friday": [],
                "Saturday": []
            }

        day = entry['day']

        if entry['type'] == "Practical":
            text = f"{entry['subject']} ({entry['faculty']}) [{entry.get('batch', '')}] ({entry.get('room', '')})"
        else:
            text = f"{entry['subject']} ({entry['faculty']}) ({entry.get('room', '')})"

        timetable[time][day].append(text)

    return render_template("class.html", timetable=timetable, cls=cls)


@app.route('/faculty')
def faculty_view():
    faculty = request.args.get('faculty')
    dept = request.args.get('department')
    year = request.args.get('year')
    term = request.args.get('term')

    docs = db.collection("timetable") \
        .where("department", "==", dept) \
        .where("year", "==", year) \
        .where("term", "==", term) \
        .where("faculty", "==", faculty) \
        .stream()

    data = [d.to_dict() for d in docs]

    timetable = {}

    for entry in data:
        time = entry['time']

        if time not in timetable:
            timetable[time] = {
                "Monday": [],
                "Tuesday": [],
                "Wednesday": [],
                "Thursday": [],
                "Friday": [],
                "Saturday": []
            }

        day = entry['day']
        text = f"{entry['subject']} ({entry['class']}) ({entry.get('room', '')})"
        timetable[time][day].append(text)

    return render_template("faculty_view.html", timetable=timetable, faculty=faculty)


@app.route('/admin/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)
