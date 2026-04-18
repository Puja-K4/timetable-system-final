from flask import Flask, render_template, request, redirect, session, flash, url_for
from firebase_config import db
import pandas as pd

app = Flask(__name__)
app.secret_key = "supersecretkey"

def normalize_text(value):
    return " ".join(str(value).strip().split())

def faculty_exists(name, department):
    docs = db.collection("faculty") \
        .where("department", "==", department) \
        .stream()

    normalized_name = normalize_text(name).lower()

    for doc in docs:
        data = doc.to_dict()
        existing_name = normalize_text(data.get("name", "")).lower()
        if existing_name == normalized_name:
            return True
    return False

def safe_list_from_collection(collection_name, field_name, department=None):
    query = db.collection(collection_name)
    if department:
        query = query.where("department", "==", department)

    values = []
    for doc in query.stream():
        data = doc.to_dict()
        if data.get(field_name):
            values.append(data[field_name])
    return values

@app.route('/')
def home():

    docs = db.collection("timetable").stream()
    data = [d.to_dict() for d in docs]

    departments = sorted(set([d.get('department') for d in data if d.get('department')]))
    years = sorted(set([d.get('year') for d in data if d.get('year')]))
    terms = sorted(set([d.get('term') for d in data if d.get('term')]))
    classes = sorted(set([d.get('class') for d in data if d.get('class')]))

    return render_template("home.html",
                           departments=departments,
                           years=years,
                           terms=terms,
                           classes=classes)

@app.route('/faculty-select')
def faculty_select():

    docs = db.collection("timetable").stream()
    data = [d.to_dict() for d in docs]

    departments = sorted(set([d['department'] for d in data]))
    years = sorted(set([d['year'] for d in data]))
    terms = sorted(set([d['term'] for d in data]))
    faculty = sorted(set([d['faculty'] for d in data]))

    return render_template("faculty_select.html",
                           departments=departments,
                           years=years,
                           terms=terms,
                           faculty=faculty)
    
# 🔐 LOGIN PAGE
@app.route('/admin/login', methods=['GET', 'POST'])
def login():

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        department = request.form['department']

        admins = db.collection("admins")\
            .where("email", "==", email)\
            .where("department", "==", department)\
            .stream()

        for admin in admins:
            data = admin.to_dict()

            if data['password'] == password:
                session['admin'] = True
                session['department'] = department
                return redirect('/admin/select-session')

        return "Invalid credentials"

    # Fetch departments for dropdown
    depts = [d.to_dict()['name'] for d in db.collection("departments").stream()]

    return render_template("login.html", departments=depts)

@app.route('/admin/select-session', methods=['GET', 'POST'])
def select_session():

    if not session.get('admin'):
        return redirect('/admin/login')

    if request.method == 'POST':
        session['year'] = request.form['year']
        session['term'] = request.form['term']
        return redirect('/admin/dashboard')

    # 🔥 Fetch all sessions
    sessions = list(db.collection("academic_sessions").stream())

    years = []
    active_year = None

    for s in sessions:
        data = s.to_dict()
        years.append(data['year'])

        if data.get('active') == True:
            active_year = data['year']

    return render_template("select_session.html",
                           years=years,
                           active_year=active_year)

# 🏠 DASHBOARD
@app.route('/admin/dashboard')
def dashboard():

    if not session.get('admin'):
        return redirect('/admin/login')

    if not session.get('year') or not session.get('term'):
        return redirect('/admin/select-session')

    return render_template("dashboard.html")

@app.route('/admin/faculty', methods=['GET', 'POST'])
def faculty():

    if not session.get('admin'):
        return redirect('/admin/login')

    dept = session.get('department')

    if request.method == 'POST':
        name = normalize_text(request.form.get('name', ''))

        if not name:
            flash("Faculty name is required.", "error")
            return redirect(url_for('faculty'))

        if faculty_exists(name, dept):
            flash("Faculty already exists in this department.", "error")
            return redirect(url_for('faculty'))

        db.collection("faculty").add({
            "name": name,
            "department": dept
        })

        flash("Faculty added successfully.", "success")
        return redirect(url_for('faculty'))

    docs = db.collection("faculty") \
        .where("department", "==", dept) \
        .stream()

    data = []
    for d in docs:
        item = d.to_dict()
        item['id'] = d.id
        data.append(item)

    return render_template("faculty.html", data=data)


@app.route('/admin/upload-master', methods=['GET', 'POST'])
def upload_master():

    if not session.get('admin'):
        return redirect('/admin/login')

    dept = session.get('department')

    if request.method == 'POST':
        file = request.files['file']

        faculty_df = pd.read_excel(file, sheet_name="Faculty")
        subjects_df = pd.read_excel(file, sheet_name="Subjects")
        classes_df = pd.read_excel(file, sheet_name="Classes")
        timeslots_df = pd.read_excel(file, sheet_name="TimeSlots")
        rooms_df = pd.read_excel(file, sheet_name="Rooms")

        for _, row in faculty_df.iterrows():
            db.collection("faculty").add({
                "name": str(row['name']).strip(),
                "department": dept
            })

        for _, row in subjects_df.iterrows():
            db.collection("subjects").add({
                "name": str(row['subject']).strip(),
                "department": dept
            })

        for _, row in classes_df.iterrows():
            db.collection("classes").add({
                "name": str(row['class']).strip(),
                "department": dept
            })

        for _, row in timeslots_df.iterrows():
            db.collection("timeslots").add({
                "slot": str(row['slot']).strip()
            })
            
        for _, row in rooms_df.iterrows():
            db.collection("rooms").add({
            "room": str(row['room']).strip()
        })

        return redirect('/admin/upload-master?success=1')

    # 👇 GET request
    success = request.args.get('success')

    return render_template("upload_master.html", success=success)

@app.route('/admin/upload-faculty', methods=['POST'])
def upload_faculty():

    if not session.get('admin'):
        return redirect('/admin/login')

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

        if faculty_exists(name, dept):
            skipped_count += 1
            continue

        db.collection("faculty").add({
            "name": name,
            "department": dept
        })

        seen_in_file.add(key)
        added_count += 1

    flash(f"Faculty upload complete. Added: {added_count}, Skipped: {skipped_count}", "success")
    return redirect(url_for('faculty'))

@app.route('/admin/delete-faculty/<id>')
def delete_faculty(id):

    if not session.get('admin'):
        return redirect('/admin/login')

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


@app.route('/admin/add-timetable', methods=['GET', 'POST'])
def add_timetable():

    if not session.get('admin'):
        return redirect('/admin/login')

    if not session.get('year') or not session.get('term'):
        return redirect('/admin/select-session')

    dept = session.get('department')

    classes = safe_list_from_collection("classes", "name", dept)
    subjects = safe_list_from_collection("subjects", "name", dept)
    faculty = safe_list_from_collection("faculty", "name", dept)
    timeslots = safe_list_from_collection("timeslots", "slot")
    rooms = safe_list_from_collection("rooms", "room")

    message = ""

    allowed_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    allowed_types = ["Theory", "Practical"]

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

        required_fields = ['year', 'term', 'class', 'day', 'time', 'subject', 'faculty', 'type', 'room']
        for field in required_fields:
            if not data[field]:
                message = f"❌ {field.capitalize()} is required."
                return render_template("add_timetable.html", **locals())

        if data['day'] not in allowed_days:
            message = "❌ Invalid day selected."
            return render_template("add_timetable.html", **locals())

        if data['type'] not in allowed_types:
            message = "❌ Invalid lecture type selected."
            return render_template("add_timetable.html", **locals())

        if data['time'] not in timeslots:
            message = "❌ Invalid time slot selected."
            return render_template("add_timetable.html", **locals())

        if data['class'] not in classes:
            message = "❌ Invalid class selected."
            return render_template("add_timetable.html", **locals())

        if data['subject'] not in subjects:
            message = "❌ Invalid subject selected."
            return render_template("add_timetable.html", **locals())

        if data['faculty'] not in faculty:
            message = "❌ Invalid faculty selected."
            return render_template("add_timetable.html", **locals())

        if data['room'] not in rooms:
            message = "❌ Invalid room selected."
            return render_template("add_timetable.html", **locals())

        if data['type'] == "Practical" and not data['batch']:
            message = "❌ Batch is required for practical."
            return render_template("add_timetable.html", **locals())

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
                return render_template("add_timetable.html", **locals())

            if c['faculty'] == data['faculty']:
                message = "❌ Faculty already assigned at this time!"
                return render_template("add_timetable.html", **locals())

            if c['room'] == data['room']:
                message = "❌ Room already occupied!"
                return render_template("add_timetable.html", **locals())

            if data['type'] == "Practical":
                if c['class'] == data['class'] and c.get('batch', '') == data.get('batch', ''):
                    message = "❌ Same batch already assigned at this time!"
                    return render_template("add_timetable.html", **locals())

        db.collection("timetable").add(data)
        message = "✅ Timetable entry added successfully!"

    return render_template("add_timetable.html", **locals())

@app.route('/department')
def department():

    dept = request.args.get('department')
    year = request.args.get('year')
    term = request.args.get('term')

    docs = db.collection("timetable")\
        .where("department","==",dept)\
        .where("year","==",year)\
        .where("term","==",term)\
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

        # 🎯 FORMAT TEXT
        if entry['type'] == "Practical":
            text = f"{entry['subject']} ({entry['faculty']}) [{entry.get('batch','')}] ({entry.get('room','')})"
        else:
            text = f"{entry['subject']} ({entry['faculty']}) ({entry.get('room','')})"

        timetable[key][day].append(text)

    return render_template("department.html",
                           timetable=timetable,
                           dept=dept,
                           year=year,
                           term=term)

@app.route('/admin/departments', methods=['GET', 'POST'])
def departments():

    if not session.get('admin'):
        return redirect('/admin/login')

    if request.method == 'POST':
        name = normalize_text(request.form.get('name', ''))

        if not name:
            flash("Department name is required.", "error")
            return redirect(url_for('departments'))

        docs = db.collection("departments").stream()
        for d in docs:
            data = d.to_dict()
            if normalize_text(data.get("name", "")).lower() == name.lower():
                flash("Department already exists.", "error")
                return redirect(url_for('departments'))

        db.collection("departments").add({
            "name": name
        })

        flash("Department added successfully.", "success")
        return redirect(url_for('departments'))

    docs = db.collection("departments").stream()

    data = []
    for d in docs:
        item = d.to_dict()
        item['id'] = d.id
        data.append(item)

    return render_template("departments.html", data=data)

@app.route('/admin/classes', methods=['GET', 'POST'])
def classes_admin():

    if not session.get('admin'):
        return redirect('/admin/login')

    dept = session.get('department')

    if request.method == 'POST':
        name = normalize_text(request.form.get('name', ''))

        if not name:
            flash("Class name is required.", "error")
            return redirect(url_for('classes_admin'))

        docs = db.collection("classes").where("department", "==", dept).stream()
        for d in docs:
            data = d.to_dict()
            if normalize_text(data.get("name", "")).lower() == name.lower():
                flash("Class already exists in this department.", "error")
                return redirect(url_for('classes_admin'))

        db.collection("classes").add({
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

    return render_template("classes.html", data=data)

@app.route('/admin/subjects', methods=['GET', 'POST'])
def subjects_admin():

    if not session.get('admin'):
        return redirect('/admin/login')

    dept = session.get('department')

    if request.method == 'POST':
        name = normalize_text(request.form.get('name', ''))

        if not name:
            flash("Subject name is required.", "error")
            return redirect(url_for('subjects_admin'))

        docs = db.collection("subjects").where("department", "==", dept).stream()
        for d in docs:
            data = d.to_dict()
            if normalize_text(data.get("name", "")).lower() == name.lower():
                flash("Subject already exists in this department.", "error")
                return redirect(url_for('subjects_admin'))

        db.collection("subjects").add({
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

    return render_template("subjects.html", data=data)

@app.route('/admin/delete-timetable/<id>')
def delete_timetable(id):

    if not session.get('admin'):
        return redirect('/admin/login')

    doc = db.collection("timetable").document(id).get()

    if not doc.exists:
        flash("Timetable entry not found.", "error")
        return redirect(url_for('add_timetable'))

    db.collection("timetable").document(id).delete()
    flash("Timetable entry deleted successfully.", "success")
    return redirect(url_for('add_timetable'))

@app.route('/admin/edit-timetable/<id>', methods=['GET', 'POST'])
def edit_timetable(id):

    if not session.get('admin'):
        return redirect('/admin/login')

    if not session.get('year') or not session.get('term'):
        return redirect('/admin/select-session')

    dept = session.get('department')

    doc = db.collection("timetable").document(id).get()

    if not doc.exists:
        flash("Timetable entry not found.", "error")
        return redirect(url_for('add_timetable'))

    entry = doc.to_dict()

    classes = safe_list_from_collection("classes", "name", dept)
    subjects = safe_list_from_collection("subjects", "name", dept)
    faculty = safe_list_from_collection("faculty", "name", dept)
    timeslots = safe_list_from_collection("timeslots", "slot")
    rooms = safe_list_from_collection("rooms", "room")

    message = ""

    allowed_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    allowed_types = ["Theory", "Practical"]

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

        required_fields = ['year', 'term', 'class', 'day', 'time', 'subject', 'faculty', 'type', 'room']
        for field in required_fields:
            if not data[field]:
                message = f"❌ {field.capitalize()} is required."
                return render_template("edit_timetable.html", entry=entry, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

        if data['day'] not in allowed_days:
            message = "❌ Invalid day selected."
            return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

        if data['type'] not in allowed_types:
            message = "❌ Invalid lecture type selected."
            return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

        if data['time'] not in timeslots:
            message = "❌ Invalid time slot selected."
            return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

        if data['class'] not in classes:
            message = "❌ Invalid class selected."
            return render_template("edit_timetable.html", entry=data, classes=classes, subjects=subjects, faculty=faculty, timeslots=timeslots, rooms=rooms, message=message)

        if data['subject'] not in subjects:
            message = "❌ Invalid subject selected."
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

    return render_template("edit_timetable.html",
                           entry=entry,
                           classes=classes,
                           subjects=subjects,
                           faculty=faculty,
                           timeslots=timeslots,
                           rooms=rooms,
                           message=message)
    
@app.route('/class')
def class_view():

    cls = request.args.get('class')
    dept = request.args.get('department')
    year = request.args.get('year')
    term = request.args.get('term')

    docs = db.collection("timetable")\
        .where("department","==",dept)\
        .where("year","==",year)\
        .where("term","==",term)\
        .where("class","==",cls)\
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
            text = f"{entry['subject']} ({entry['faculty']}) [{entry.get('batch','')}] ({entry.get('room','')})"
        else:
            text = f"{entry['subject']} ({entry['faculty']}) ({entry.get('room','')})"

        timetable[time][day].append(text)
    
    print("Class:", cls)
    print("Dept:", dept)
    print("Year:", year)
    print("Term:", term)

    return render_template("class.html",
                           timetable=timetable,
                           cls=cls)

@app.route('/faculty')
def faculty_view():

    faculty = request.args.get('faculty')
    dept = request.args.get('department')
    year = request.args.get('year')
    term = request.args.get('term')

    docs = db.collection("timetable")\
        .where("department","==",dept)\
        .where("year","==",year)\
        .where("term","==",term)\
        .where("faculty","==",faculty)\
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

        text = f"{entry['subject']} ({entry['class']}) ({entry.get('room','')})"

        timetable[time][day].append(text)

    return render_template("faculty_view.html",
                           timetable=timetable,
                           faculty=faculty)
       
# 🚪 LOGOUT
@app.route('/admin/logout')
def logout():
    session.clear()
    return redirect('/admin/login')


if __name__ == '__main__':
    app.run(debug=True)