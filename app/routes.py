from flask import Flask, render_template, redirect, url_for, request, flash, Blueprint, session, json
from flask_login import login_user, logout_user, current_user
from sqlalchemy import desc, func, distinct
from collections import Counter
from .db import db, Entry, User
from .forms import LogginForm, SignUpForm, AddEntryForm, SearchForm, UserProfileToggle, UserStatisticsForm

routes = Blueprint('routes', __name__, template_folder='templates')

def get_args_and_redirect(form, username=None):
    search_query = form.search_query.data
    search_order = form.search_order.data
    specialty = form.specialty.data
    note_type = form.note_type.data
    note_part = form.note_part.data
    if username:
        profile_display_type = form.profile_display_type.data
        return redirect(url_for('routes.view_profile',
            username=username,
            profile_display_type=profile_display_type,
            q=search_query, search_order=search_order,
            specialty=specialty,
            note_type=note_type,
            note_part=note_part))
    else:
        return redirect(url_for('routes.show_entries', username=username, q=search_query, search_order=search_order,
            specialty=specialty, note_type=note_type, note_part=note_part))

def flatten_tags(*args):
    tags = []
    for arg in args:
        if arg:
            for tag in arg:
                tags.append(tag)
    return tags

def apply_query_string(entries, q):
    if q:
        entries = entries.filter((Entry.description.contains(q)) \
            | (Entry.template.contains(q)))
    else:
        entries = Entry.query
    return entries

def apply_tags(entries, tags):
    if tags:
        for tag in tags:
            entries = entries.filter(Entry.tags.contains(tag))
    return entries

def paginate_results(entries, search_order, page):
    if search_order == 'saves':
        pagination = entries.order_by(desc(Entry.num_user_saves)).paginate(page, per_page=30, error_out=False)
    else:
        pagination = entries.order_by(desc(Entry.time_created)).paginate(page, per_page=30, error_out=False)
    return pagination

def generate_entry_query(entries):
    entry_ids = []
    for entry in entries:
        entry_ids.append(entry.id)
    return Entry.query.filter(Entry.id.in_(entry_ids))


@routes.route('/')
def show_landing():
    return render_template('landing.html')

@routes.route('/test_entries')
def gen_test_entries():
    User.generate_fake(20)
    Entry.generate_fake()
    return redirect(url_for('routes.show_entries'))


@routes.route('/log_out')
def log_out():
    logout_user()
    flash("you were logged out")
    return redirect(url_for('routes.show_landing'))

@routes.route('/log_in', methods=['GET', 'POST'])
def show_log_in():
    username = None
    form = LogginForm()
    if form.validate_on_submit():
        username = form.name.data
        password = form.password.data
        form.name.data = ""
        form.password.data = ""
        user = User.query.filter(User.name == username.lower()).first()
        if user is not None and user.verify_password(password):
            session['user'] = username
            flash("sign in successful")
            login_user(user, form.remember_me.data)
            return redirect(url_for("routes.view_profile", username=username))
        else:
            flash("incorrect username or password. sign up if you have not signed up!")
            return redirect(url_for("routes.show_log_in"))
    return render_template('log_in.html', form=form)

@routes.route('/sign_up', methods=['GET', 'POST'])
def show_sign_up():
    username = None
    form = SignUpForm()
    if form.validate_on_submit():
        username = form.name.data
        institution = form.institution.data
        password = form.password.data
        profession = form.profession.data
        specialty = form.specialty.data
        already_signed_up = User.query.filter(User.name == username.lower()).first()
        if not already_signed_up:
            new_user = User(name=username,
                institution=institution,
                password=password,
                profession=profession,
                specialty=specialty)
            db.session.add(new_user)
            db.session.commit()
            flash("sign up successful")
            login_user(new_user)
            return redirect(url_for("routes.view_profile", username=username))
        else:
            flash("username already in database - choose something else")
            return redirect(url_for('routes.show_sign_up'))
    else:
        professions = ['Physician', 'Nurse Practitioner', 'Physicians Assistant']
        return render_template('sign_up.html', form=form, professions=professions)



@routes.route('/show_entries', methods=['GET', 'POST'])
def show_entries():
    form = SearchForm()
    entry_list = []
    if form.validate_on_submit():
        response = get_args_and_redirect(form)
        return response

    if request.method == "POST":
        request_type = list(request.form.keys())
        if "save_entry" in request_type:
            entry_id = int(request.form["save_entry"])
            entry = Entry.query.filter(Entry.id == entry_id).one()
            user = User.query.filter(User.name == current_user.name).one()
            print(entry)
            print(user)
            message = ""
            if entry in user.submissions:
                message = "You cannot save an entry you have submitted"
                status = "Error"
            elif entry in user.saved_entries:
                message = "You have already saved this entry"
                status = "Error"
            else:
                if entry.num_user_saves == 0:
                    entry.user_saves = [user]
                else:
                    entry.user_saves.append(user)
                entry.num_user_saves += 1

                db.session.add_all([user, entry])
                db.session.commit()
                status = 'OK'

            return json.dumps({'status': status, "data" : [message, entry.num_user_saves]});
        elif "update_template" in request_type:
            template_id = request.form['update_template']
            current_display = request.form['current_template']
            entry_id = int(template_id[9:])
            entry = Entry.query.filter(Entry.id == entry_id).one()
            if len(current_display) < len(entry.template):
                return_template, action = entry.template, 'expand'
            else:
                return_template, action = entry.template_display, 'shrink'
            return json.dumps({'return_template': return_template, "action" : action})

    else:
        q = request.args.get('q')
        search_order = request.args.get('search_order')
        specialty = request.args.getlist('specialty')
        note_part = request.args.getlist('note_part')
        note_type = request.args.getlist('note_type')
        page = request.args.get('page', 1, type=int)
        profile_display_type = request.args.get('profile_display_type')
        username = request.args.get('username')

        tags = flatten_tags(specialty, note_type, note_part)

        entries = Entry.query
        entries = apply_query_string(entries, q)
        entries = apply_tags(entries, tags)
        pagination = paginate_results(entries, search_order, page)

        endpoint = '.show_entries'
        entries = pagination.items

        # preserve form values
        form.search_query.data = q
        if search_order:
            form.search_order.data = search_order
        else:
            form.search_order.data = 'submission_time'
        form.specialty.data = specialty
        form.note_part.data = note_part
        form.note_type.data = note_type

        return render_template('entries.html',
            entries=entries,
            pagination=pagination,
            form=form,
            endpoint=endpoint,
            q=q,
            search_order=search_order,
            specialty=specialty,
            note_part=note_part,
            note_type=note_type,
            profile_display_type=profile_display_type)


@routes.route('/add', methods=['GET', 'POST'])
def add_entry():
    form = AddEntryForm()
    if form.validate_on_submit():
        description = form.description.data
        template = form.template.data
        user = current_user
        specialty_tag = form.specialty.data
        note_type_tag = form.note_type.data
        note_part_tag = form.note_part.data
        remember_tags = form.remember_tags.data

        tags = flatten_tags(specialty_tag, note_type_tag, note_part_tag)
        tags = sorted(tags)
        tags = ', '.join(tags)

        entry = Entry(description=description, template=template, user=user, tags=tags)
        db.session.add(entry)
        db.session.commit()
        flash("entry added")
        return redirect(url_for('routes.add_entry', remember_tags=remember_tags, specialty=specialty_tag, note_part=note_part_tag, note_type=note_type_tag))
    else:
        remember_tags = request.args.get('remember_tags')
        if remember_tags:
            form.specialty.data = request.args.getlist('specialty')
            form.note_part.data = request.args.getlist('note_part')
            form.note_type.data = request.args.getlist('note_type')
            form.remember_tags.data = request.args.get('remember_tags')
        return render_template('add_entries.html', form=form)

@routes.route('/users', methods=['GET', 'POST'])
def show_users():
    page = request.args.get('page', 1, type=int)
    form = UserStatisticsForm()
    if form.validate_on_submit():
        display_order = form.display_order.data
        return redirect(url_for('routes.show_users', display_order=display_order))

    display_order = request.args.get('display_order', 'date_enrolled')
    form.display_order.data = display_order
    endpoint = 'routes.show_users'

    if display_order == 'date_enrolled':
        pagination = User.query.order_by(desc(User.time_enrolled)).paginate(page, per_page=50, error_out=False)
        users = pagination.items
        return render_template('users.html', form=form, users=users, endpoint=endpoint, pagination=pagination, display_order=display_order)

    # descending order of user saves
    # returns a keyedtuple that can accessed via integers / slices
    elif display_order == 'saves':
        users = db.session.query(User, Entry.user_id, func.sum(Entry.num_user_saves).label('save_sums')).join(Entry).\
            group_by(Entry.user_id).\
            order_by(desc('save_sums'))
        users = [(user[0], int(user[2])) for user in users]
        return render_template('user_saves.html', form=form, users=users)

    # submissions by institution
    elif display_order == 'institution':
        institution_stats = db.session.query(User.institution, func.count(distinct(User.id)).label('user_count'), func.count(Entry.id).label('entry_count')).\
            join(Entry).\
            group_by(User.institution).order_by(desc('entry_count'))
        return render_template('institution_stats.html', form=form, institution_stats=institution_stats)

    # order by submissions
    else:
        submission_order = db.session.query(User, func.count(Entry.id).label('sub_count')).\
            join(Entry).\
            group_by(User.name).order_by(desc('sub_count'))
        return render_template('submission_stats.html', form=form, submission_order=submission_order)


    es = db.session.query(User, Entry.user_id, func.sum(Entry.num_user_saves).label('save_sums')).join(Entry).\
        group_by(Entry.user_id).\
        order_by(desc('save_sums'))


@routes.route('/view_profile/<username>', methods=['GET', 'POST'])
def view_profile(username):
    # this will delete entries if delete button is pressed
    form = UserProfileToggle()
    if form.validate_on_submit():
        response = get_args_and_redirect(form, username)
        return response

    if request.method == "POST":
        print("success");
        entry_id = int(request.form['entry_id'])
        entry_type = request.form['entry_type']
        entry = Entry.query.filter(Entry.id == entry_id)
        if entry_type == 'submission':
            entry.delete()
            db.session.commit()
        elif entry_type == 'saved':
            user = User.query.filter(User.name == current_user.name).first()
            entry = entry.one()
            print(user)
            saved_entries = user.saved_entries
            saved_entries = [entry for entry in saved_entries if entry.id != entry_id]
            user.saved_entries = saved_entries
            entry.num_user_saves -= 1
            db.session.add_all([user, entry])
            db.session.commit()
        else:
            raise KeyError
        return json.dumps({'status':'OK'});
    else:
        q = request.args.get('q')
        search_order = request.args.get('search_order', 'submission_time')
        specialty = request.args.getlist('specialty')
        note_part = request.args.getlist('note_part')
        note_type = request.args.getlist('note_type')
        page = request.args.get('page', 1, type=int)
        profile_display_type = request.args.get('profile_display_type', 'Submitted')

        if current_user.is_anonymous or current_user.name != username:
            current = False
            user = User.query.filter(User.name == username).one()
            username = user.name
        else:
            user = current_user
            username = user.name
            current = True

        tags = flatten_tags(specialty, note_type, note_part)
        if profile_display_type == 'Submitted':
            entries = generate_entry_query(user.submissions)
            username_display = "{} - submitted entries".format(username)
        else:
            entries = generate_entry_query(user.saved_entries)
            username_display = "{} - saved entries".format(username)

        entries = apply_query_string(entries, q)
        entries = apply_tags(entries, tags)
        pagination = paginate_results(entries, search_order, page)
        entries = pagination.items

        # preserve form values
        if search_order:
            form.search_order.data = search_order
        else:
            form.search_order.data = 'submission_time'
        form.specialty.data = specialty
        form.note_part.data = note_part
        form.note_type.data = note_type
        form.profile_display_type.data = profile_display_type
        form.search_order.data = search_order
        form.search_query.data = q
        endpoint = '.view_profile'

        return render_template('user_profile.html',
            pagination=pagination,
            endpoint=endpoint,
            entries=entries,
            username_display=username_display,
            user=user,
            current=current,
            form=form,
            q=q,
            search_order=search_order,
            specialty=specialty,
            note_part=note_part,
            note_type=note_type,
            profile_display_type=profile_display_type)
