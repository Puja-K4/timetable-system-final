from flask import Flask, render_template, request, redirect, session
from firebase_config import db
import pandas as pd

app = Flask(__name__)
app.secret_key = "supersecretkey"


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
        name = request.form['name']

        db.collection("faculty").add({
            "name": name,
            "department": dept
        })

    docs = db.collection("faculty")\
        .where("department", "==", dept)\
        .stream()

    data = []
    for d in docs:
        item = d.to_dict()
        item['id'] = d.id
        data.append(item)

    return render_template("faculty.html", data=data)

import pandas as pd

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

    file = request.files['file']
    df = pd.read_excel(file)

    dept = session.get('department')

    for _, row in df.iterrows():
        db.collection("faculty").add({
            "name": row['name'],
            "department": dept
        })

    return redirect('/admin/faculty')

@app.route('/admin/delete-faculty/<id>')
def delete_faculty(id):

    if not session.get('admin'):
        return redirect('/admin/login')

    db.collection("faculty").document(id).delete()
    return redirect('/admin/faculty')


@app.route('/admin/add-timetable', methods=['GET', 'POST'])
def add_timetable():

    if not session.get('year') or not session.get('term'):
        return redirect('/admin/select-session')

    dept = session.get('department')

    # 🔹 Fetch dropdown data
    classes = [c.to_dict()['name'] for c in db.collection("classes").where("department","==",dept).stream()]
    subjects = [s.to_dict()['name'] for s in db.collection("subjects").where("department","==",dept).stream()]
    faculty = [f.to_dict()['name'] for f in db.collection("faculty").where("department","==",dept).stream()]
    timeslots = [t.to_dict()['slot'] for t in db.collection("timeslots").stream()]
    rooms = [r.to_dict()['room'] for r in db.collection("rooms").stream()]

    message = ""

    if request.method == 'POST':

        data = {
            "department": dept,
            "year": request.form['year'],
            "term": request.form['term'],
            "class": request.form['class'],
            "day": request.form['day'],
            "time": request.form['time'],
            "subject": request.form['subject'],
            "faculty": request.form['faculty'],
            "type": request.form['type'],
            "batch": request.form.get('batch', ''),
            "room": request.form['room']
        }

        # 🚨 CONFLICT DETECTION
        conflicts = db.collection("timetable")\
            .where("day","==",data['day'])\
            .where("time","==",data['time'])\
            .where("department","==",dept)\
            .stream()

        for c in conflicts:
            c = c.to_dict()

            # 🚫 CLASS CLASH (ONLY FOR THEORY)
            if data['type'] == "Theory":
                if c['class'] == data['class']:
                    message = "❌ Class already has lecture at this time!"
                    return render_template("add_timetable.html", **locals())

            # 🚫 FACULTY CLASH
            if c['faculty'] == data['faculty']:
                message = "❌ Faculty already assigned at this time!"
                return render_template("add_timetable.html", **locals())

            # 🚫 ROOM CLASH
            if c['room'] == data['room']:
                message = "❌ Room already occupied!"
                return render_template("add_timetable.html", **locals())

            # 🚫 PRACTICAL SAME BATCH CLASH
            if data['type'] == "Practical":
                if c['class'] == data['class'] and c.get('batch') == data.get('batch'):
                    message = "❌ Same batch already assigned!"
                    return render_template("add_timetable.html", **locals())

        # ✅ SAVE
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