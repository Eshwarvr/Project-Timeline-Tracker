from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
from datetime import date
import plotly.express as px
import plotly.graph_objects as go
import json

app = Flask(__name__)

# Add this custom filter after your imports
@app.template_filter('ddmmyyyy')
def format_date_ddmmyyyy(date_obj):
    """Format date as DD-MM-YYYY"""
    if date_obj:
        return date_obj.strftime('%d-%m-%Y')
    return ''

def to_title_case(text):
    """Convert text to title case"""
    if text:
        return text.strip().title()
    return text

def calculate_completion_percentage(project):
    """Calculate project completion based on milestones"""
    if not project.milestones:
        return 0
    
    completed = sum(1 for m in project.milestones if m.status == 'Completed')
    return int((completed / len(project.milestones)) * 100)

def get_milestone_status(milestone, today=None):
    """
    Calculate milestone status based on dates and user-set status
    Returns: 'Not Started', 'In Progress', 'Completed', or 'Overdue'
    """
    if today is None:
        today = datetime.now().date()
    
    # If user marked as Completed, return Completed
    if milestone.status == 'Completed':
        return 'Completed'
    
    # If user marked as In Progress, check if overdue
    if milestone.status == 'In Progress':
        if milestone.end_date < today:
            return 'Overdue'  # Overdue means end_date passed but not completed
        return 'In Progress'
    
    # If status is 'Not Started' or anything else, auto-detect
    if today < milestone.start_date:
        return 'Not Started'  # Before start date
    elif today > milestone.end_date:
        return 'Overdue'  # After end date, not completed
    else:
        return 'In Progress'  # Between start and end date

# Database configuration
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'timeline_tracker.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db = SQLAlchemy(app)

# Database Models
class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column(db.String(200), nullable=False)
    client_name = db.Column(db.String(200), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now())
    status = db.Column(db.String(20), default='Not Completed')
    # Relationship to milestones
    milestones = db.relationship('Milestone', backref='project', lazy=True, cascade='all, delete-orphan')
    
    @property
    def completion_percentage(self):
        """Calculate project completion percentage"""
        if not self.milestones:
            return 0
        completed = sum(1 for m in self.milestones if m.status == 'Completed')
        return int((completed / len(self.milestones)) * 100)
    
    def __repr__(self):
        return f'<Project {self.project_name}>'


class Milestone(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    milestone_name = db.Column(db.String(200), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(50), default='Not Started')
    priority = db.Column(db.String(20), default='Medium')
    
    def __repr__(self):
        return f'Milestone {self.milestone_name}'


# Routes
@app.route('/')
def dashboard():
    projects = Project.query.all()
    total_projects = len(projects)
    active_projects = 0
    completed_milestones = 0
    pending_milestones = 0
    overdue_count = 0
    today = datetime.now().date()
    
    for project in projects:
        # Automatically update project status based on date logic
        if project.status != 'Completed':  
            if project.end_date < today:  
                project.status = 'Overdue'
            elif project.start_date <= today:  
                project.status = 'In Progress'
            else:
                project.status = 'Not Started'
    
    db.session.commit()
    
    for project in projects:
        # Count active projects (all non-completed projects)
        if project.status != 'Completed':
            active_projects += 1
        
        # Count overdue projects ONLY (not individual milestones)
        if project.status == 'Overdue':
            overdue_count += 1
        
        for milestone in project.milestones:
            if milestone.status == 'Completed':
                completed_milestones += 1
            else:
                pending_milestones += 1
            
            # Update milestone status if overdue (but don't count it)
            if milestone.end_date < today and milestone.status != 'Completed':
                milestone.status = 'Overdue'
        
        db.session.commit()
    
    return render_template('dashboard.html',
                         projects=projects,
                         total_projects=total_projects,
                         active_projects=active_projects,
                         completed_milestones=completed_milestones,
                         pending_milestones=pending_milestones,
                         overdue_count=overdue_count,
                         today=today)


@app.route('/add-project', methods=['GET', 'POST'])
def add_project():
    if request.method == 'POST':
        # Convert to title case
        project_name = to_title_case(request.form['project_name'])
        client_name = to_title_case(request.form['client_name'])
        # HTML date inputs submit YYYY-MM-DD; parse accordingly
        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()
        
        # Check if project with same name exists
        existing_project = Project.query.filter_by(project_name=project_name).first()
        if existing_project:
            from flask import flash
            flash(f'A project with the name "{project_name}" already exists!', 'warning')
            return render_template('add_project.html', 
                                   prefill_project=project_name, 
                                   prefill_client=client_name)
        
        new_project = Project(
            project_name=project_name,
            client_name=client_name,
            start_date=start_date,
            end_date=end_date
        )
        
        db.session.add(new_project)
        db.session.commit()
        return redirect(url_for('dashboard'))
    
    return render_template('add_project.html')

@app.route('/toggle-status/<int:project_id>', methods=['POST'])
def toggle_status(project_id):
    project = Project.query.get_or_404(project_id)
    today = datetime.now().date()
    
    if project.status == 'Completed':
        # User wants to mark as Not Completed
        project.status = 'Not Completed'
        # Auto-update based on date
        if project.end_date < today:
            project.status = 'Overdue'
        elif project.start_date <= today:
            project.status = 'In Progress'
        else:
            project.status = 'Not Started'
    else:
        # User wants to mark as Completed
        # Check if all milestones are completed
        all_completed = True
        for milestone in project.milestones:
            actual_status = get_milestone_status(milestone, today)
            if actual_status != 'Completed':
                all_completed = False
                break
        
        if all_completed:
            project.status = 'Completed'
        else:
            # Don't allow completion - flash message or just don't change
            # For now, we'll just not change the status
            pass
    
    db.session.commit()
    return redirect(url_for('view_project', project_id=project.id))

@app.route('/project/<int:project_id>')
def view_project(project_id):
    project = Project.query.get_or_404(project_id)
    today = datetime.now().date()

    # Calculate milestone statistics and actual statuses
    completed_milestones_count = 0
    total_milestones = len(project.milestones)

    for milestone in project.milestones:
        # Calculate actual status based on dates and user input
        actual_status = get_milestone_status(milestone, today)
        
        # Update in database for consistency
        if milestone.status != actual_status:
            milestone.status = actual_status
        
        # Count completed
        if actual_status == 'Completed':
            completed_milestones_count += 1

    db.session.commit()

    # Calculate completion percentage
    completion_percentage = 0
    if total_milestones > 0:
        completion_percentage = round((completed_milestones_count / total_milestones) * 100)

    return render_template('view_project.html',
        project=project,
        today=date.today(),
        completed_milestones=completed_milestones_count,
        total_milestones=total_milestones,
        completion_percentage=completion_percentage)



@app.route('/add-milestone/<int:project_id>', methods=['GET', 'POST'])
def add_milestone(project_id):
    project = Project.query.get_or_404(project_id)
    
    if request.method == 'POST':
        # Convert to title case
        milestone_name = to_title_case(request.form['milestonename'])
        start_date = datetime.strptime(request.form['startdate'], '%Y-%m-%d').date()
        end_date = datetime.strptime(request.form['enddate'], '%Y-%m-%d').date()
        status = request.form['status']
        priority = request.form.get('priority', 'Medium')
        
        # Validation...
        if start_date < project.start_date:
            error = f"Milestone start date cannot be before project start date ({project.start_date})"
            return render_template('add_milestone.html', project=project, error=error)
        
        if end_date > project.end_date:
            error = f"Milestone end date cannot be after project end date ({project.end_date})"
            return render_template('add_milestone.html', project=project, error=error)
        
        if start_date > end_date:
            error = "Milestone start date cannot be after end date"
            return render_template('add_milestone.html', project=project, error=error)
        
        new_milestone = Milestone(
            project_id=project_id,
            milestone_name=milestone_name,
            start_date=start_date,
            end_date=end_date,
            status=status,
            priority=priority
        )
        
        db.session.add(new_milestone)
        db.session.commit()
        return redirect(url_for('view_project', project_id=project_id))
    
    return render_template('add_milestone.html', project=project)


@app.route('/edit-milestone/<int:milestone_id>', methods=['GET', 'POST'])
def edit_milestone(milestone_id):
    milestone = Milestone.query.get_or_404(milestone_id)
    project_id = milestone.project_id
    project = Project.query.get_or_404(project_id)
    
    if request.method == 'POST':
        old_status = milestone.status
        
        # Convert to title case
        milestone.milestone_name = to_title_case(request.form['milestonename'])
        start_date = datetime.strptime(request.form['startdate'], '%Y-%m-%d').date()
        end_date = datetime.strptime(request.form['enddate'], '%Y-%m-%d').date()
        new_status = request.form['status']
        milestone.priority = request.form.get('priority', 'Medium')
        
        # Validation...
        if start_date < project.start_date:
            error = f"Milestone start date cannot be before project start date ({project.start_date})"
            return render_template('edit_milestone.html', milestone=milestone, project=project, error=error)
        
        if end_date > project.end_date:
            error = f"Milestone end date cannot be after project end date ({project.end_date})"
            return render_template('edit_milestone.html', milestone=milestone, project=project, error=error)
        
        if start_date > end_date:
            error = "Milestone start date cannot be after end date"
            return render_template('edit_milestone.html', milestone=milestone, project=project, error=error)
        
        milestone.start_date = start_date
        milestone.end_date = end_date
        milestone.status = new_status
        
        db.session.commit()
        
        if old_status == 'Completed' and new_status != 'Completed':
            project.status = 'Not Completed'
            db.session.commit()
        
        return redirect(url_for('view_project', project_id=project_id))
    
    return render_template('edit_milestone.html', milestone=milestone, project=project)


@app.route('/edit-project/<int:project_id>', methods=['GET', 'POST'])
def edit_project(project_id):
    """Edit existing project details"""
    project = Project.query.get_or_404(project_id)
    
    if request.method == 'POST':
        # Convert to title case
        new_project_name = to_title_case(request.form['project_name'])
        new_client_name = to_title_case(request.form['client_name'])
        
        # Check if changing to a name that already exists (and it's not the current project)
        if new_project_name != project.project_name:
            existing_project = Project.query.filter_by(project_name=new_project_name).first()
            if existing_project:
                from flask import flash
                flash(f'A project with the name "{new_project_name}" already exists!', 'warning')
                return render_template('edit_project.html', project=project, error=f'A project with the name "{new_project_name}" already exists!')
        
        project.project_name = new_project_name
        project.client_name = new_client_name
        
        # Parse dates
        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()
        
        # Validation
        if start_date > end_date:
            error = "Start date cannot be after end date"
            return render_template('edit_project.html', project=project, error=error)
        
        if end_date < start_date:
            error = "End date must be after start date"
            return render_template('edit_project.html', project=project, error=error)
        
        project.start_date = start_date
        project.end_date = end_date
        
        db.session.commit()
        return redirect(url_for('view_project', project_id=project.id))
    
    return render_template('edit_project.html', project=project)

@app.route('/gantt-chart')
def gantt_chart():
    projects = Project.query.all()
    
    # Convert projects and milestones to dictionaries for JSON serialization
    projects_data = []
    for project in projects:
        project_dict = {
            'id': project.id,
            'project_name': project.project_name,
            'client_name': project.client_name,
            'start_date': project.start_date.strftime('%Y-%m-%d'),
            'end_date': project.end_date.strftime('%Y-%m-%d'),
            'status': project.status,
            'completion_percentage': project.completion_percentage or 0,
            'milestones': []
        }
        
        # Add milestones
        for milestone in project.milestones:
            milestone_dict = {
                'id': milestone.id,
                'milestone_name': milestone.milestone_name,
                'start_date': milestone.start_date.strftime('%Y-%m-%d'),
                'end_date': milestone.end_date.strftime('%Y-%m-%d'),
                'status': milestone.status,
                'priority': milestone.priority or 'Medium'
            }
            project_dict['milestones'].append(milestone_dict)
        
        projects_data.append(project_dict)
    
    today = date.today()
    current_month_start = today.replace(day=1)
    total_milestones = sum(len(p.milestones) for p in projects)
    
    return render_template('gantt_chart.html',
                         projects=projects_data,
                         today=today,
                         current_month_start=current_month_start,
                         total_milestones=total_milestones)

@app.route('/api/gantt-data-filtered')
def get_filtered_gantt_data():
    """Get gantt data for specific date range"""
    start_date = request.args.get('start')
    end_date = request.args.get('end')
    
    if start_date and end_date:
        start = datetime.fromisoformat(start_date).date()
        end = datetime.fromisoformat(end_date).date()
        
        projects = Project.query.filter(
            (Project.start_date <= end) & (Project.end_date >= start)
        ).all()
    else:
        projects = Project.query.all()

@app.route('/api/autocomplete-projects', methods=['GET'])
def autocomplete_projects():
    """Return list of existing project names for autocomplete"""
    search_term = request.args.get('term', '')
    
    if search_term:
        # Search for projects that start with the search term (case-insensitive)
        projects = Project.query.filter(
            Project.project_name.ilike(f'{search_term}%')
        ).distinct().all()
        
        suggestions = [{'value': p.project_name, 'label': p.project_name} for p in projects]
    else:
        # Return all unique project names
        projects = Project.query.distinct(Project.project_name).all()
        suggestions = [{'value': p.project_name, 'label': p.project_name} for p in projects]
    
    return jsonify(suggestions)


@app.route('/api/autocomplete-clients', methods=['GET'])
def autocomplete_clients():
    """Return list of existing client names for autocomplete"""
    search_term = request.args.get('term', '')
    
    if search_term:
        # Search for clients that start with the search term (case-insensitive)
        clients = db.session.query(Project.client_name).filter(
            Project.client_name.ilike(f'{search_term}%')
        ).distinct().all()
        
        suggestions = [{'value': c[0], 'label': c[0]} for c in clients]
    else:
        # Return all unique client names
        clients = db.session.query(Project.client_name).distinct().all()
        suggestions = [{'value': c[0], 'label': c[0]} for c in clients]
    
    return jsonify(suggestions)


@app.route('/api/check-project-exists', methods=['GET'])
def check_project_exists():
    """Check if a project with the given name already exists"""
    project_name = request.args.get('name', '')
    
    if project_name:
        # Convert to title case for comparison
        project_name_title = to_title_case(project_name)
        existing_project = Project.query.filter_by(project_name=project_name_title).first()
        
        if existing_project:
            return jsonify({
                'exists': True,
                'message': f'A project named "{project_name_title}" already exists.',
                'project_id': existing_project.id
            })
    
    return jsonify({'exists': False})


########################################


@app.route('/delete-project/<int:project_id>')
def delete_project(project_id):
    project = Project.query.get_or_404(project_id)
    db.session.delete(project)
    db.session.commit()
    return redirect(url_for('dashboard'))


@app.route('/delete-milestone/<int:milestone_id>')
def delete_milestone(milestone_id):
    milestone = Milestone.query.get_or_404(milestone_id)
    project_id = milestone.project_id
    db.session.delete(milestone)
    db.session.commit()
    return redirect(url_for('view_project', project_id=project_id))

# Add this route to your app.py file

@app.route('/delete-milestones', methods=['POST'])
def delete_milestones():
    """Bulk delete milestones"""
    milestone_ids_str = request.form.get('milestone_ids', '')
    
    if not milestone_ids_str:
        flash('No milestones selected', 'warning')
        return redirect(request.referrer or url_for('index'))
    
    # Parse milestone IDs
    try:
        milestone_ids = [int(id.strip()) for id in milestone_ids_str.split(',') if id.strip()]
    except ValueError:
        flash('Invalid milestone IDs', 'error')
        return redirect(request.referrer or url_for('index'))
    
    # Get project ID for redirect
    first_milestone = Milestone.query.get(milestone_ids[0]) if milestone_ids else None
    project_id = first_milestone.project_id if first_milestone else None
    
    # Delete milestones
    deleted_count = 0
    for milestone_id in milestone_ids:
        milestone = Milestone.query.get(milestone_id)
        if milestone:
            db.session.delete(milestone)
            deleted_count += 1
    
    db.session.commit()
    
    # Show success message
    if deleted_count > 0:
        flash(f'Successfully deleted {deleted_count} milestone(s)!', 'success')
    else:
        flash('No milestones were deleted', 'warning')
    
    # Redirect back to project view
    if project_id:
        return redirect(url_for('view_project', project_id=project_id))
    else:
        return redirect(url_for('index'))


@app.route('/update-milestone-status/<int:milestone_id>', methods=['POST'])
def update_milestone_status(milestone_id):
    milestone = Milestone.query.get_or_404(milestone_id)
    new_status = request.form.get('status')
    if new_status:
        milestone.status = new_status
        db.session.commit()
    return redirect(url_for('view_project', project_id=milestone.project_id))


def home():
    return "Timeline Tracker is Running!"


if __name__ == '__main__':
    app.run(debug=True)