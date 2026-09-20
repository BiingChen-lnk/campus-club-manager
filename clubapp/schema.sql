CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, student_no VARCHAR(255) NOT NULL UNIQUE, name VARCHAR(255) NOT NULL,
 password_hash VARCHAR(255) NOT NULL, major VARCHAR(255) NOT NULL DEFAULT '', grade VARCHAR(255) NOT NULL DEFAULT '',
 phone VARCHAR(255) NOT NULL DEFAULT '', role VARCHAR(255) NOT NULL DEFAULT 'student' CHECK(role IN ('admin','student')),
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS clubs (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, name VARCHAR(255) NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT ('')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS departments (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, club_id INTEGER NOT NULL, name VARCHAR(255) NOT NULL,
 UNIQUE(club_id,name)
,
 FOREIGN KEY (club_id) REFERENCES clubs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS memberships (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, club_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
 department_id INTEGER, role VARCHAR(255) NOT NULL DEFAULT 'member' CHECK(role IN ('owner','member')),
 status VARCHAR(255) NOT NULL DEFAULT 'active' CHECK(status IN ('active','left')),
 joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(club_id,user_id)
,
 FOREIGN KEY (club_id) REFERENCES clubs(id),
 FOREIGN KEY (user_id) REFERENCES users(id),
 FOREIGN KEY (department_id) REFERENCES departments(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS batches (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, club_id INTEGER NOT NULL, title VARCHAR(255) NOT NULL,
 description TEXT NOT NULL DEFAULT (''), starts_at DATETIME NOT NULL, ends_at DATETIME NOT NULL,
 status VARCHAR(255) NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published','closed')), created_by INTEGER NOT NULL,
 CHECK(starts_at < ends_at)
,
 FOREIGN KEY (club_id) REFERENCES clubs(id),
 FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS batch_options (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, batch_id INTEGER NOT NULL, department_id INTEGER NOT NULL,
 UNIQUE(batch_id,department_id)
,
 FOREIGN KEY (batch_id) REFERENCES batches(id),
 FOREIGN KEY (department_id) REFERENCES departments(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS applications (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, batch_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
 option_id INTEGER NOT NULL, name VARCHAR(255) NOT NULL, student_no VARCHAR(255) NOT NULL,
 major VARCHAR(255) NOT NULL, grade VARCHAR(255) NOT NULL, phone VARCHAR(255) NOT NULL, experience TEXT NOT NULL DEFAULT (''), reason TEXT NOT NULL,
 interests TEXT NOT NULL DEFAULT (''), skill_text TEXT NOT NULL DEFAULT (''),
 status VARCHAR(255) NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','rejected')),
 reviewed_by INTEGER, review_note TEXT NOT NULL DEFAULT (''), reviewed_at DATETIME,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(batch_id,user_id)
,
 FOREIGN KEY (batch_id) REFERENCES batches(id),
 FOREIGN KEY (user_id) REFERENCES users(id),
 FOREIGN KEY (option_id) REFERENCES batch_options(id),
 FOREIGN KEY (reviewed_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS availability (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, application_id INTEGER NOT NULL, slot VARCHAR(255) NOT NULL,
 UNIQUE(application_id,slot)
,
 FOREIGN KEY (application_id) REFERENCES applications(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS skills (id INTEGER PRIMARY KEY AUTO_INCREMENT, name VARCHAR(255) NOT NULL UNIQUE) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS application_skills (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, application_id INTEGER NOT NULL, skill_id INTEGER NOT NULL,
 source VARCHAR(255) NOT NULL CHECK(source IN ('self','ai')), confirmed INTEGER NOT NULL DEFAULT 0 CHECK(confirmed IN (0,1)),
 evidence TEXT NOT NULL DEFAULT (''), UNIQUE(application_id,skill_id)
,
 FOREIGN KEY (application_id) REFERENCES applications(id),
 FOREIGN KEY (skill_id) REFERENCES skills(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS activities (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, club_id INTEGER NOT NULL, created_by INTEGER NOT NULL,
 title VARCHAR(255) NOT NULL, description TEXT NOT NULL, location VARCHAR(255) NOT NULL,
 starts_at DATETIME NOT NULL, ends_at DATETIME NOT NULL, deadline DATETIME NOT NULL, capacity INTEGER NOT NULL CHECK(capacity > 0),
 status VARCHAR(255) NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','pending','published','rejected','cancelled','ended')),
 CHECK(deadline <= starts_at AND starts_at < ends_at)
,
 FOREIGN KEY (club_id) REFERENCES clubs(id),
 FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS activity_approvals (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, activity_id INTEGER NOT NULL, reviewer_id INTEGER NOT NULL,
 decision VARCHAR(255) NOT NULL CHECK(decision IN ('approved','rejected')), note TEXT NOT NULL DEFAULT (''),
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
,
 FOREIGN KEY (activity_id) REFERENCES activities(id),
 FOREIGN KEY (reviewer_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS registrations (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, activity_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
 status VARCHAR(255) NOT NULL DEFAULT 'registered' CHECK(status IN ('registered','cancelled')), checked_at DATETIME,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(activity_id,user_id)
,
 FOREIGN KEY (activity_id) REFERENCES activities(id),
 FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS feedback (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, registration_id INTEGER NOT NULL UNIQUE,
 organization INTEGER NOT NULL CHECK(organization BETWEEN 1 AND 5), content INTEGER NOT NULL CHECK(content BETWEEN 1 AND 5),
 venue INTEGER NOT NULL CHECK(venue BETWEEN 1 AND 5), comment TEXT NOT NULL DEFAULT (''),
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
,
 FOREIGN KEY (registration_id) REFERENCES registrations(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ai_records (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, requested_by INTEGER NOT NULL, application_id INTEGER,
 activity_id INTEGER, kind VARCHAR(255) NOT NULL CHECK(kind IN ('recruit','plan','review')),
 input_text MEDIUMTEXT NOT NULL, output_text MEDIUMTEXT NOT NULL DEFAULT (''), status VARCHAR(255) NOT NULL CHECK(status IN ('success','failed')),
 model VARCHAR(255) NOT NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CHECK((application_id IS NOT NULL AND activity_id IS NULL AND kind='recruit') OR
       (activity_id IS NOT NULL AND application_id IS NULL AND kind IN ('plan','review')))
,
 FOREIGN KEY (requested_by) REFERENCES users(id),
 FOREIGN KEY (application_id) REFERENCES applications(id),
 FOREIGN KEY (activity_id) REFERENCES activities(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS retrospectives (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, activity_id INTEGER NOT NULL UNIQUE, body TEXT NOT NULL,
 edited_by INTEGER NOT NULL, ai_record_id INTEGER,
 updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
,
 FOREIGN KEY (activity_id) REFERENCES activities(id),
 FOREIGN KEY (edited_by) REFERENCES users(id),
 FOREIGN KEY (ai_record_id) REFERENCES ai_records(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS fund_applications (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, club_id INTEGER NOT NULL, activity_id INTEGER,
 applicant_id INTEGER NOT NULL, purpose TEXT NOT NULL,
 status VARCHAR(255) NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
,
 FOREIGN KEY (club_id) REFERENCES clubs(id),
 FOREIGN KEY (activity_id) REFERENCES activities(id),
 FOREIGN KEY (applicant_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS budget_items (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, fund_id INTEGER NOT NULL, name VARCHAR(255) NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity > 0), unit_cents INTEGER NOT NULL CHECK(unit_cents > 0)
,
 FOREIGN KEY (fund_id) REFERENCES fund_applications(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS fund_approvals (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, fund_id INTEGER NOT NULL, reviewer_id INTEGER NOT NULL,
 decision VARCHAR(255) NOT NULL CHECK(decision IN ('approved','rejected')), note TEXT NOT NULL DEFAULT (''),
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
,
 FOREIGN KEY (fund_id) REFERENCES fund_applications(id),
 FOREIGN KEY (reviewer_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS transactions (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, club_id INTEGER NOT NULL, activity_id INTEGER,
 fund_id INTEGER, recorded_by INTEGER NOT NULL,
 direction VARCHAR(255) NOT NULL CHECK(direction IN ('income','expense')), amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
 category VARCHAR(255) NOT NULL, happened_on DATE NOT NULL, note TEXT NOT NULL DEFAULT (''),
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CHECK(direction='income' OR fund_id IS NOT NULL)
,
 FOREIGN KEY (club_id) REFERENCES clubs(id),
 FOREIGN KEY (activity_id) REFERENCES activities(id),
 FOREIGN KEY (fund_id) REFERENCES fund_applications(id),
 FOREIGN KEY (recorded_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS receipts (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, transaction_id INTEGER NOT NULL, uploaded_by INTEGER NOT NULL,
 filename VARCHAR(255) NOT NULL, storage_name VARCHAR(255) NOT NULL UNIQUE,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
,
 FOREIGN KEY (transaction_id) REFERENCES transactions(id),
 FOREIGN KEY (uploaded_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS notifications (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, recipient_id INTEGER NOT NULL, content TEXT NOT NULL,
 read_at DATETIME, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
,
 FOREIGN KEY (recipient_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_logs (
 id INTEGER PRIMARY KEY AUTO_INCREMENT, actor_id INTEGER, club_id INTEGER,
 action VARCHAR(255) NOT NULL, object_type VARCHAR(255) NOT NULL, object_id INTEGER, detail TEXT NOT NULL DEFAULT (''),
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
,
 FOREIGN KEY (actor_id) REFERENCES users(id),
 FOREIGN KEY (club_id) REFERENCES clubs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
