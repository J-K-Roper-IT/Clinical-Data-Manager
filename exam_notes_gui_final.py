import tkinter as tk
from tkinter import ttk
import psycopg2
from datetime import datetime
from db_config import DB_PARAMS
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from tkinter import messagebox
import os
import textwrap  # make sure this is at the top of your script
from datetime import datetime, date

def wrap_description(label, text, indent=20, width=80):
    # Align text after the label, first line starts with label, rest get indented
    initial_indent = ' ' * indent + f"{label:<13}"
    subsequent_indent = ' ' * (indent + 13)
    return textwrap.fill(str(text or ''), width=width, initial_indent=initial_indent, subsequent_indent=subsequent_indent)
        
def format_two_col(label1, value1, label2, value2, col_width=20):
    return f"{label1:<{col_width}} {str(value1 or ''):<25} {label2:<{col_width}} {str(value2 or '')}"    

class PatientExamSelector(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.conn = psycopg2.connect(**DB_PARAMS)
        self.patient_var = tk.StringVar()
        self.exam_var = tk.StringVar()
        self.create_widgets()
        self.pack(fill='both', expand=True)

    def create_widgets(self):
        tk.Label(self, text="Search Patient:").pack(anchor='w')
        self.patient_entry = tk.Entry(self, textvariable=self.patient_var)
        self.patient_entry.pack(fill='x')
        self.patient_entry.bind('<KeyRelease>', self.filter_patients)

        self.patient_listbox = tk.Listbox(self, height=5)
        self.patient_listbox.pack(fill='x')
        self.patient_listbox.bind('<<ListboxSelect>>', self.select_patient)

        tk.Label(self, text="Select Exam:").pack(anchor='w')
        self.exam_dropdown = ttk.Combobox(self, textvariable=self.exam_var)
        self.exam_dropdown.pack(fill='x')
        self.exam_dropdown.configure(state='normal')
        self.exam_dropdown.bind('<<ComboboxSelected>>', self.select_exam)

        tk.Label(self, text="Preview:").pack(anchor='w', pady=(10, 0))
        self.preview_text = tk.Text(self, height=35, wrap='word', font=("Courier", 10))
        self.preview_text.pack(fill='both', expand=True)

        self.generate_button = tk.Button(self, text="Generate PDF", command=self.generate_pdf)
        self.generate_button.pack(pady=10)

    def filter_patients(self, event=None):
        typed = self.patient_var.get().lower()
        if typed.strip() == "":
            self.patient_listbox.delete(0, tk.END)
            return

        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT id, first_name || ' ' || last_name AS full_name
                FROM patient
                WHERE lower(first_name || ' ' || last_name) LIKE %s
                ORDER BY first_name ASC, last_name ASC
            """, (typed + '%',))
            self.patient_results = cur.fetchall()

        self.patient_listbox.delete(0, tk.END)
        for _, name in self.patient_results:
            self.patient_listbox.insert(tk.END, name)

    def select_patient(self, event):
        selection = self.patient_listbox.curselection()
        if selection:
            index = selection[0]
            patient_id, name = self.patient_results[index]
            self.patient_var.set(name)
            self.patient_listbox.delete(0, tk.END)
            self.load_exams_for_patient(patient_id)

    def fetch_exam_physical(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT additional_testing_notes, visual_fields_method_cf,
                    visual_fields_method_auto, vf_comment_text,
                    pupils_dim_od, pupils_bright_od, pupils_direct_od,
                    pupils_dim_os, pupils_bright_os, pupils_direct_os,
                    pupils_shape_od_text, pupils_shape_os_text,
                    pupils_apd, pupils_comments
                FROM exam_physical
                WHERE exam_id = %s
            """, (exam_id,))
            row = cur.fetchone()

        keys = [
            'additional_testing_notes', 'visual_fields_method_cf',
            'visual_fields_method_auto', 'vf_comment_text',
            'pupils_dim_od', 'pupils_bright_od', 'pupils_direct_od',
            'pupils_dim_os', 'pupils_bright_os', 'pupils_direct_os',
            'pupils_shape_od_text', 'pupils_shape_os_text',
            'pupils_apd', 'pupils_comments'
        ]
        return dict(zip(keys, row)) if row else {key: '' for key in keys}

    def load_exams_for_patient(self, patient_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT exam_id
                FROM v_patient_exams
                WHERE patient_id = %s
                ORDER BY exam_id DESC
            """, (patient_id,))
            exams = [str(row[0]) for row in cur.fetchall()]

        self.exam_dropdown['values'] = exams
        if exams:
            self.exam_dropdown.set(exams[0])
            self.select_exam()

    def select_exam(self, event=None):
        exam_id = self.exam_var.get().strip()
        if exam_id.isdigit():
            self.load_exam_preview(exam_id)

    def fetch_header_data(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    ve.exam_id,
                    p.first_name,
                    p.last_name,
                    LEFT(p.first_name, 1) AS initial,
                    TO_CHAR(p.date_of_birth, 'Month DD, YYYY') AS dob,
                    p.gender,
                    TO_CHAR(ve.exam_date, 'Mon, Mon DD, YYYY') AS exam_date,
                    TO_CHAR(ve.exam_date, 'Mon, Mon DD, YYYY') AS last_exam_date,
                    hf.physician_name,
                    TO_CHAR(e.start_time, 'HH12:MI AM') AS start_time,
                    TO_CHAR(e.end_time, 'HH12:MI AM') AS end_time,
                    EXTRACT(EPOCH FROM (e.end_time - e.start_time)) / 60 AS face_time,
                    EXTRACT(EPOCH FROM (e.end_time - e.start_time)) / 60 AS counsel_time,
                    e.exam_label AS exam_type
                FROM public.v_patient_exams ve
                JOIN public.patient p ON ve.patient_id = p.id
                JOIN public.exam e ON ve.exam_id = e.id
                LEFT JOIN public.hcfa_form hf ON hf.id = ve.exam_id
                WHERE ve.exam_id = %s
            """, (exam_id,))
            row = cur.fetchone()

        if row:
            keys = ['exam_id', 'first_name', 'last_name', 'initial', 'dob', 'gender',
                    'exam_date', 'last_exam_date', 'physician_name',
                    'start_time', 'end_time', 'face_time', 'counsel_time', 'exam_type']
            return dict(zip(keys, row))
        return {}
        
    def fetch_exam_medications(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT medication_name, medication_for
                FROM public.exam_current_medication
                WHERE exam_id = %s
                ORDER BY id ASC
            """, (exam_id,))
            rows = cur.fetchall()
        return [row[0] for row in rows if row[0]]
    
    def get_patient_id_from_exam(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("SELECT patient_id FROM v_patient_exams WHERE exam_id = %s", (exam_id,))
            result = cur.fetchone()
            return result[0] if result else None
        
    def fetch_allergies(self, patient_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    allergen_name,
                    reaction,
                    onset_date
                FROM
                    rcopia_allergy
                WHERE
                    patient_id = %s
                  AND deleted = FALSE
                ORDER BY onset_date DESC
            """, (patient_id,))
            return cur.fetchall()
        
    def fetch_electronic_medications(self, patient_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT d.brand_name, d.generic_name, m.start_date, m.stop_date
                FROM rcopia_medication m
                LEFT JOIN rcopia_drug d ON m.sig_drug_id = d.id
                WHERE m.patient_id = %s AND m.deleted = FALSE
                ORDER BY m.start_date DESC
            """, (patient_id,))
            return cur.fetchall()

    def fetch_diagnosis_and_procedures(self, exam_id):
        with self.conn.cursor() as cur:
            # Diagnosis code and description
            cur.execute("""
                SELECT dc.code, dc.description
                FROM diagnostic_code dc
                JOIN exam e ON e.diagnostic_code_id = dc.id
                WHERE e.id = %s
            """, (exam_id,))
            diag = cur.fetchone()
            diagnosis_code, diagnosis_description = (diag if diag else ('', ''))

            # Procedural codes and related diagnosis - assuming structure
            cur.execute("""
                SELECT code, description, related_diagnosis
                FROM exam_procedures
                WHERE exam_id = %s
            """, (exam_id,))
            procedures = cur.fetchall()
            procedure_codes = "; ".join([p[0] for p in procedures]) if procedures else ''
            related_diagnosis = "; ".join([p[2] for p in procedures if p[2]]) if procedures else ''

        return diagnosis_code, diagnosis_description, procedure_codes, related_diagnosis

    def fetch_chief_complaint(self, exam_id):
        with self.conn.cursor() as cur:
            # HPI core fields
            cur.execute("""
                SELECT
                    ecc.chief_complaint,
                    ecc.is_chief,
                    eh.location,
                    eh.quality,
                    eh.severity,
                    eh.duration,
                    eh.timing,
                    eh.context,
                    eh.modifying_factors,
                    eh.symptoms,
                    ecc.comments
                FROM exam_case_history ech
                JOIN exam_chief_complaints ecc ON ecc.exam_case_history_id = ech.id
                JOIN exam_hpi eh ON eh.exam_chief_complaints_id = ecc.id
                WHERE ech.exam_id = %s
            """, (exam_id,))
            result = cur.fetchone()

            # Pull narrative & reviewed from exam_case_history
            cur.execute("""
                SELECT hpi_narrative, hpi_reviewed
                FROM exam_case_history
                WHERE exam_id = %s
            """, (exam_id,))
            narrative_row = cur.fetchone()

        return {
            "chief_complaint": result[0] if result else "<CHIEF_COMPLAINT_PLACEHOLDER>",
            "is_chief": "Yes" if result and result[1] else "No",
            "hpi_location": result[2] if result else "<HPI_LOCATION>",
            "hpi_quality": result[3] if result else "<HPI_QUALITY>",
            "hpi_severity": result[4] if result else "<HPI_SEVERITY>",
            "hpi_duration": result[5] if result else "<HPI_DURATION>",
            "hpi_timing": result[6] if result else "<HPI_TIMING>",
            "hpi_context": result[7] if result else "<HPI_CONTEXT>",
            "hpi_modifying_factors": result[8] if result else "<HPI_MODIFYING>",
            "hpi_signs_symptoms": result[9] if result else "<HPI_SIGNS>",
            "hpi_comments": result[10] if result else "<NO_HPI_COMMENTS>",  # ✅ 🔄 ADDED
            "hpi_narrative": narrative_row[0] if narrative_row and narrative_row[0] else "<NO_NOTES>",
            "hpi_reviewed": "Yes" if narrative_row and narrative_row[1] else "No"
        }
    
    def fetch_diagnosis_and_procedures(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    emdc.diagnosis_string,
                    dc.description
                FROM exam_medical_decision_code emdc
                LEFT JOIN diagnostic_code dc ON dc.identifier = emdc.diagnosis_string
                WHERE emdc.exam_medical_decision_id = %s
                ORDER BY emdc.id ASC
                LIMIT 1
            """, (exam_id,))
            diag = cur.fetchone()

        diagnosis_code, diagnosis_description = (diag if diag else ('', ''))
        return diagnosis_code, diagnosis_description

            # Procedural codes and related diagnosis - assuming structure
        cur.execute("""
            SELECT code, description, related_diagnosis
            FROM exam_procedures
            WHERE exam_id = %s
        """, (exam_id,))
        procedures = cur.fetchall()
        procedure_codes = "; ".join([p[0] for p in procedures]) if procedures else ''
        related_diagnosis = "; ".join([p[2] for p in procedures if p[2]]) if procedures else ''

        return diagnosis_code, diagnosis_description, procedure_codes, related_diagnosis

    def fetch_objective_refraction(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    obj_refract_instrument_used,
                    obj_refract_pd_mm,
                    obj_refract_od_a, obj_refract_od_b, obj_refract_od_c, obj_refract_od_d,
                    obj_refract_os_a, obj_refract_os_b, obj_refract_os_c, obj_refract_os_d,
                    obj_refract_ou_d,
                    obj_refract_comments
                FROM exam_physical
                WHERE exam_id = %s;
            """, (exam_id,))
            return cur.fetchone()

    def fetch_exam_pupils(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    pupils_dim_od, pupils_dim_os,
                    pupils_bright_od, pupils_bright_os,
                    pupils_direct_od, pupils_direct_os,
                    pupils_shape_od_text, pupils_shape_os_text,
                    pupils_apd, pupils_comments
                FROM exam_physical
                WHERE exam_id = %s
            """, (exam_id,))
            row = cur.fetchone()
            if not row:
                return {}

            return {
                'od_dim': row[0], 'os_dim': row[1],
                'od_bright': row[2], 'os_bright': row[3],
                'od_direct': row[4], 'os_direct': row[5],
                'od_shape': row[6], 'os_shape': row[7],
                'apd': row[8], 'comments': row[9]
            }

    def fetch_exam_motility(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    cover_test,
                    dist_a, dist_b, near_a, near_b,
                    dist_amt, near_amt,
                    dist_hyper_amt, near_hyper_amt,
                    dist_hyper_active, near_hyper_active,
                    dist_hyper, near_hyper,
                    comment,
                    eom_full_range, eom_limited, eom_choppy, eom_smooth, eom_head_mov
                FROM exam_motility
                WHERE exam_id = %s
            """, (exam_id,))
            row = cur.fetchone()

        if row:
            return {
                'cover_test': row[0],
                'dist_a': row[1],
                'dist_b': row[2],
                'near_a': row[3],
                'near_b': row[4],
                'dist_amt': row[5],
                'near_amt': row[6],
                'dist_hyper_amt': row[7],
                'near_hyper_amt': row[8],
                'dist_hyper_active': row[9],
                'near_hyper_active': row[10],
                'dist_hyper': row[11],
                'near_hyper': row[12],
                'comment': row[13],
                'eom_full_range': row[14],
                'eom_limited': row[15],
                'eom_choppy': row[16],
                'eom_smooth': row[17],
                'eom_head_mov': row[18]
            }
        else:
            # Return empty/default values if no data
            return {
                'cover_test': '',
                'dist_a': '', 'dist_b': '', 'near_a': '', 'near_b': '',
                'dist_amt': '', 'near_amt': '',
                'dist_hyper_amt': '', 'near_hyper_amt': '',
                'dist_hyper_active': '', 'near_hyper_active': '',
                'dist_hyper': '', 'near_hyper': '',
                'comment': '',
                'eom_full_range': '', 'eom_limited': '',
                'eom_choppy': '', 'eom_smooth': '', 'eom_head_mov': ''
            }

    def fetch_final_cl_prescriptions(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    sphere_od, cylinder_od, axis_od, add_od,
                    sphere_os, cylinder_os, axis_os, add_os,
                    bc_od, diameter_od, manufacturer_od, lens_type_od, tint_od,
                    bc_os, diameter_os, manufacturer_os, lens_type_os, tint_os,
                    expiration_date, cmt
                FROM cl_prescription
                WHERE exam_id = %s AND final_rx = TRUE
                ORDER BY ordinal;
            """, (exam_id,))
            return cur.fetchall()

    def check_or_graybox(self, val, label):
        return f"✓ {label}" if val else f"□ {label}"
    
    def fetch_exam_gonioscopy(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    gonioscopy_od_open360, gonioscopy_os_open360,
                    gonioscopy_od_st_opento, gonioscopy_os_st_opento,
                    gonioscopy_od_st_narrow, gonioscopy_os_st_narrow,
                    gonioscopy_od_sn_opento, gonioscopy_od_sn_narrow,
                    gonioscopy_os_sn_opento, gonioscopy_os_sn_narrow,
                    gonioscopy_od_it_opento, gonioscopy_od_it_narrow,
                    gonioscopy_os_it_opento, gonioscopy_os_it_narrow,
                    gonioscopy_od_in_opento_, gonioscopy_od_in_narrow,
                    gonioscopy_os_in_opento, gonioscopy_os_in_narrow
                FROM exam_slit
                WHERE exam_id = %s
            """, (exam_id,))
            row = cur.fetchone()

        keys = [
            'od_360', 'os_360',
            'st_od_open', 'st_os_open', 'st_od_narrow', 'st_os_narrow',
            'sn_od_open', 'sn_od_narrow', 'sn_os_open', 'sn_os_narrow',
            'it_od_open', 'it_od_narrow', 'it_os_open', 'it_os_narrow',
            'in_od_open', 'in_od_narrow', 'in_os_open', 'in_os_narrow'
        ]
        return dict(zip(keys, row)) if row else {k: None for k in keys}

    def fetch_exam_pharmaceutical(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    pharmaceutical_od,
                    pharmaceutical_os,
                    pharmaceutical_ou,
                    pharmaceutical_comment,
                    concentration_od,
                    concentration_os,
                    concentration_ou,
                    concentration_comment,
                    other_dx_drugs_od,
                    other_dx_drugs_os,
                    other_dx_drugs_ou,
                    other_dx_drugs_comment
                FROM exam_slit
                WHERE exam_id = %s
            """, (exam_id,))
            row = cur.fetchone()

        if not row:
            return {}

        keys = [
            'pharmaceutical_od', 'pharmaceutical_os', 'pharmaceutical_ou', 'pharmaceutical_comment',
            'concentration_od', 'concentration_os', 'concentration_ou', 'concentration_comment',
            'other_dx_drugs_od', 'other_dx_drugs_os', 'other_dx_drugs_ou', 'other_dx_drugs_comment'
        ]
        return dict(zip(keys, row))

    def load_exam_preview(self, exam_id):
        self.preview_text.delete('1.0', tk.END)

        data = self.fetch_header_data(exam_id)
        if not data:
            self.preview_text.insert(tk.END, f"⚠️ No header data returned for Exam ID {exam_id}\n")
            return

        patient_id = self.get_patient_id_from_exam(exam_id)
        chief = self.fetch_chief_complaint(exam_id)
        allergies = self.fetch_allergies(patient_id)
        ros_data = self.fetch_ros_flags(exam_id)
        va_data = self.fetch_visual_acuity_and_vitals(exam_id)
        pretest = self.fetch_full_pretesting_data(exam_id)
        exam_physical = self.fetch_exam_physical(exam_id)
        coding = self.fetch_exam_coding(exam_id)
        diagnosis_code = coding['dx_code']
        diagnosis_description = coding['dx_desc']
        procedure_codes = f"{coding['cpt1']['code']}; {coding['cpt2']['code']}".strip("; ")
        related_diagnosis = f"{coding['cpt1']['dx']}; {coding['cpt2']['dx']}".strip("; ")
        exam_physical = self.fetch_exam_physical(exam_id)

        output = []

        # Normalize gender display
        gender_lookup = {'M': 'Male', 'F': 'Female'}
        gender = gender_lookup.get(data.get('gender', '').strip().upper(), data.get('gender', ''))

       #  Generate Checkmark for script usage
        def checkmark(value):
            return "✓" if value else " " 
        
        # Normalize times: blank if None
        start_time = data.get('start_time') or ''
        end_time = data.get('end_time') or ''
        face_time = f"{data.get('face_time') or ''} min"
        counsel_time = f"{data.get('counsel_time') or ''} min"

        # Add report title
        output.append("=== Eyecare Examination Form ===\n")

        # Header block with patient info
        output.append(f"Exam ID: {data['exam_id']}")
        output.append("")  # Blank line for spacing
        output.append(f"""Date Printed: {datetime.now().strftime("%m/%d/%Y %I:%M %p")}
Last Name: {data['last_name']}    First Name: {data['first_name']}    Initial: {data['initial']}
Date of Birth: {data['dob']}    Gender: {gender}
Exam Date: {data['exam_date']}      Last Exam: {data['last_exam_date']}
Exam Type: {data['exam_type']}    Provider: {data['physician_name']}
Doctor Start Time: {start_time}    Doctor End Time: {end_time}
Total face-to-face time: {face_time}    Counseling & coordination time: {counsel_time}
""")


        output.append("=== Encounter History ===\nAllergies:")
        allergy_lines = ["Allergy         Reaction                 Onset Date"]
        if allergies:
            for a, r, o in allergies:
                onset = o.strftime('%Y-%m-%d') if o else ''
                allergy_lines.append(f"{a:<15} {r:<25} {onset}")
        else:
            allergy_lines.append("<No known allergies>")
        output.append("\n".join(allergy_lines) + "\n")

        output.append("=== Chief Complaint / Reason for Visit: ===")       
        output.append(f"Chief: {chief['is_chief']}")
        output.append("Complaint and History of Present Illness (HPI):")
        output.append(chief['chief_complaint'])

        output.append("")  # blank line
        output.append("HPI Breakdown:")
        output.append(f"Location: {chief['hpi_location']}     Quality: {chief['hpi_quality']}     Severity: {chief['hpi_severity']}     Duration: {chief['hpi_duration']}")
        output.append(f"Timing: {chief['hpi_timing']}     Context: {chief['hpi_context']}     Modifying Factors: {chief['hpi_modifying_factors']}")
        output.append(f"Associated Signs or Symptoms: {chief['hpi_signs_symptoms']}")
        output.append(f"Comment: {chief['hpi_comments']}")  # 🔄 ADDED

        output.append("\nCurrent Medications (Manual Entry)")
        output.append("Medication Name                     Reason")
        manual_meds = self.fetch_exam_medications(exam_id)
        if manual_meds:
            for med in manual_meds:
                output.append(f"A  {med:<30} no medications")
        else:
            output.append("A  no medications")

        output.append("\nCurrent Medications (Electronic Entry)    No information recorded")
        output.append("Brand Name                     Medication Name               Start Date     Stop Date")

        electronic_meds = self.fetch_electronic_medications(patient_id)
        if electronic_meds:
            for brand, generic, start, stop in electronic_meds:
                start_fmt = start.strftime('%m/%d/%Y') if start else ''
                stop_fmt = stop.strftime('%m/%d/%Y') if stop else ''
                output.append(f"{brand:<30} {generic:<25} {start_fmt:<12} {stop_fmt}")


        pfsh = self.fetch_pfsh_data(exam_id)
        output.append("")  # Blank line for spacing

        output.append("=== Past, Family & Social History (PFSH) ===")

        # 🧠 Past Section
        output.append("Past")

        past_ocular_list = []
        if pfsh.get("past_ocular_glc"): past_ocular_list.append("- GLC")
        if pfsh.get("past_ocular_amd"): past_ocular_list.append("- AMD")
        if pfsh.get("past_ocular_cat"): past_ocular_list.append("- CAT")
        if pfsh.get("past_ocular_ca"):  past_ocular_list.append("- CA")
        if pfsh.get("past_ocular_dr"):  past_ocular_list.append("- DR")
        if pfsh.get("past_ocular_surgery"): past_ocular_list.append("- Surgery")
        output.append("Ocular:  " + "  ".join(past_ocular_list) if past_ocular_list else "Ocular:")

        past_medical_list = []
        if pfsh.get("past_medical_htn"):  past_medical_list.append("- HTN")
        if pfsh.get("past_medical_chol"): past_medical_list.append("- CHOL")
        if pfsh.get("past_medical_dm"):   past_medical_list.append("- DM")
        output.append("Medical: " + "  ".join(past_medical_list) if past_medical_list else "Medical:")

        past_other = pfsh.get("past_medical_other_text", "").strip()
        output.append(f"Other:   {past_other}" if past_other else "Other:")

        # 🧠 Family Section
        output.append("")
        output.append("Family")

        family_ocular_list = []
        if pfsh.get("family_ocular_glc"): family_ocular_list.append("- GLC")
        if pfsh.get("family_ocular_cat"): family_ocular_list.append("- CAT")
        if pfsh.get("family_ocular_amd"): family_ocular_list.append("- AMD")
        output.append("Ocular:  " + "  ".join(family_ocular_list) if family_ocular_list else "Ocular:")

        family_medical_list = []
        if pfsh.get("family_medical_htn"): family_medical_list.append("- HTN")
        if pfsh.get("family_medical_dm"):  family_medical_list.append("- DM")
        output.append("Medical: " + "  ".join(family_medical_list) if family_medical_list else "Medical:")

        family_other = pfsh.get("family_medical_other_text", "").strip()
        output.append(f"Other:   {family_other}" if family_other else "Other:")
        output.append("")  # Blank line for spacing

        #  
        output.append("=== Review of Systems (ROS) ===")
        output.append("Primary ROS taken today")
        output.append("System                              Status")
        output.append("-" * 50)

        ros_labels = [
            "Allergic/Immunologic", "Eyes", "Musculoskeletal", "Cardiovascular", "Gastrointestinal",
            "Neurological", "Constitutional", "Genitourinary", "Psychiatric",
            "Ears, Nose, Mouth & Throat", "Hematologic/Lymphatic", "Respiratory",
            "Endocrine", "Integumentary"
        ]

        for label in ros_labels:
            val = ros_data.get(label, '').strip().lower()
            normalized = "Yes" if val == "yes" else "Neg."
            # Pad manually so "Yes"/"Neg." always starts at char position 50
            line = f"{label}"
            while len(line) < 38:
                line += " "
            line += normalized
            output.append(line)

        output.append("")  # Blank line for spacing
        output.append("=== Brief Assessment of Mental Status ===")
        output.append("[X] Noted orientation to time, place and person")
        output.append("[X] Noted mood and affect\n")

        output.append("=== Pretesting ===")
        output.append(f"Color Vision")
        output.append(f"OD: {pretest.get('cv_od', ''):<5}  Type of test: {pretest.get('cv_test_od', '')}")
        output.append(f"OS: {'':<5}  Type of test: {pretest.get('cv_test_os', '')}")
        output.append(f"Stereo")
        output.append(f"Score: {pretest.get('stereo_score', ''):<8}  Type of test: {pretest.get('stereo_test', '')}")
        output.append("")  # Blank line for spacing
        output.append("Corneal Topography")
        output.append("        H Diopters    H Axis    V Diopters    V Axis")
        output.append(f"OD:     {pretest.get('topo_h_od', ''):<13}{pretest.get('topo_h_axis_od', ''):<10}{pretest.get('topo_v_od', ''):<14}{pretest.get('topo_v_axis_od', '')}")
        output.append(f"OS:     {pretest.get('topo_h_os', ''):<13}{pretest.get('topo_h_axis_os', ''):<10}{pretest.get('topo_v_os', ''):<14}{pretest.get('topo_v_axis_os', '')}")
        output.append("")  # Blank line for spacing
        mires_od = pretest.get('k_mires_od', '')
        mires_os = pretest.get('k_mires_os', '')
        mires_od_display = f"{mires_od:<10}" if mires_od else " " * 1 + "None"
        mires_os_display = f"{mires_os:<10}" if mires_os else " " * 1 + "None"
        output.append("Keratometry")
        output.append("        H Diopters    H Axis    V Diopters    V Axis    Mires")
        output.append(
            f"OD:     {pretest.get('k_h_od', ''):<13}"
            f"{pretest.get('k_h_axis_od', ''):<10}"
            f"{pretest.get('k_v_od', ''):<14}"
            f"{pretest.get('k_v_axis_od', ''):<10}"
            f"{mires_od_display}"
        )
        output.append(
            f"OS:     {pretest.get('k_h_os', ''):<13}"
            f"{pretest.get('k_h_axis_os', ''):<10}"
            f"{pretest.get('k_v_os', ''):<14}"
            f"{pretest.get('k_v_axis_os', ''):<10}"
            f"{mires_os_display}"
        )
        output.append("")  # Blank line for spacing 
        output.append("Tonometry")
        output.append(f"OD: {pretest.get('tono_od', ''):<8}OS: {pretest.get('tono_os', '')}")
        output.append(f"Eye Drop: {pretest.get('eye_drop', ''):<10}Oculus: {pretest.get('oculus', ''):<10}Method: {pretest.get('method', '')}")

        output.append("")  # Blank line for spacing 
        output.append("=== Visual Acuity ===")       
        output.append("Un-Aided")
        output.append("         Dist       16\"       Pinhole")
        output.append(f"OD:     {va_data.get('va_unaided_dist_od', ''):<10}{va_data.get('va_unaided_16_od', ''):<10}{va_data.get('va_unaided_ph_od', '')}")
        output.append(f"OS:     {va_data.get('va_unaided_dist_os', ''):<10}{va_data.get('va_unaided_16_os', ''):<10}{va_data.get('va_unaided_ph_os', '')}")
        output.append(f"OU:     {va_data.get('va_unaided_dist_ou', ''):<10}{va_data.get('va_unaided_16_ou', ''):<10}{va_data.get('va_unaided_ph_ou', '')}")
        output.append("")  # Blank line for spacing
        output.append("Aided")
        output.append("         Dist       16\"       Pinhole")
        output.append(f"OD:     {va_data.get('va_aided_dist_od', ''):<10}{va_data.get('va_aided_16_od', ''):<10}{va_data.get('va_aided_ph_od', '')}")
        output.append(f"OS:     {va_data.get('va_aided_dist_os', ''):<10}{va_data.get('va_aided_16_os', ''):<10}{va_data.get('va_aided_ph_os', '')}")
        output.append(f"OU:     {va_data.get('va_aided_dist_ou', ''):<10}{va_data.get('va_aided_16_ou', ''):<10}{va_data.get('va_aided_ph_ou', '')}")

        # --- VITALS SECTION ---
        output.append("")  # Blank line for spacing        
        output.append("=== Vitals ===")
        output.append(f"Height {va_data.get('height_ft', '0')} ft {va_data.get('height_in', '0')} in")
        output.append(f"Weight {va_data.get('weight_lb', '0')} lb")
        output.append(f"BMI: {str(va_data.get('bmi') or '')}")
        bp_a = va_data.get('bp_a') or ''
        bp_b = va_data.get('bp_b') or ''
        bp_str = f"{bp_a} / {bp_b}" if bp_a and bp_b else ''
        output.append(f"Blood Pressure: {bp_str}")
        output.append(f"Blood Sugar: {str(va_data.get('blood_sugar') or '')}")
        output.append(f"A1C: {str(va_data.get('a1c') or '')}")
        output.append(f"Heart Rate: {str(va_data.get('heart_rate') or '')}")
        output.append(f"Body Temperature: {str(va_data.get('body_temp') or '')}")
        output.append(f"O2% Bldc Oximetry: {str(va_data.get('oxygen_saturation') or '')}")
        output.append(f"Respiratory Rate: {str(va_data.get('resp_rate') or '')}")
        output.append(f"Inhaled Oxygen Concentration: {str(va_data.get('inhaled_o2') or '')}")
        output.append(f"Time: {str(va_data.get('vitals_time') or '')}")


        specs = self.fetch_spec_prescriptions(exam_id)

        # Ensure these are always fetched regardless of specs presence
        ret = self.fetch_retinoscopy(exam_id)
        subj = self.fetch_subjective_refraction(exam_id)
        cyclo = self.fetch_cycloplegic_refraction(exam_id)

        output.append("")  # Blank line for spacing
        output.append("=== Refraction ===")

        output.append("=== Final Spectacle Prescription ===")
        for i in (1, 2):  # 1 = Primary, 2 = Secondary
            label = "Primary" if i == 1 else "Secondary"
            data = specs.get(i)
            if not data:
                continue

            output.append(f"\n{label} Spectacle  Expiration Date: {data.get('expiration', '')}")
            output.append("       Sphere   Cylinder  Axis   Add   Dist Acuity")
            output.append("      Sphere   Cylinder  Axis   Add    V Prism  Base   H Prism  Base   Dist Acuity   Near Acuity   Dist PD  Near PD")
            output.append(f"OD:   {data.get('sphere_od', ''):<8} {data.get('cylinder_od', ''):<9} {data.get('axis_od', ''):<6} {data.get('add_od', ''):<6} {'':<8} {'':<6} {'':<8} {'':<6} {data.get('dist_acuity_od', ''):<13} {data.get('near_acuity_od', ''):<13} {'':<8} {'':<8}")
            output.append(f"OS:   {data.get('sphere_os', ''):<8} {data.get('cylinder_os', ''):<9} {data.get('axis_os', ''):<6} {data.get('add_os', ''):<6} {'':<8} {'':<6} {'':<8} {'':<6} {data.get('dist_acuity_os', ''):<13} {data.get('near_acuity_os', ''):<13} {'':<8} {'':<8}")
            output.append(f"OU:   {'':<8} {'':<9} {'':<6} {'':<6} {'':<8} {'':<6} {'':<8} {'':<6} {data.get('dist_acuity_ou', ''):<13} {data.get('near_acuity_ou', ''):<13} {'':<8} {'':<8}")

            if data.get('recommend'):
                output.append(f"Recommendations: {data['recommend']}")

        # Tertiary Spectacle block, simplified fallback
        tertiary = specs.get(3)
        if tertiary:
            output.append(f"\nTertiary Spectacle  Expiration Date: {tertiary.get('expiration', '')}")
            output.append(f"OD: Sphere: {tertiary.get('sphere_od', '')}  Cylinder: {tertiary.get('cylinder_od', '')}  Axis: {tertiary.get('axis_od', '')}  Add: {tertiary.get('add_od', '')}")
            output.append(f"OS: Sphere: {tertiary.get('sphere_os', '')}  Cylinder: {tertiary.get('cylinder_os', '')}  Axis: {tertiary.get('axis_os', '')}  Add: {tertiary.get('add_os', '')}")
            output.append(f"OU: Acuity: {tertiary.get('dist_acuity_ou', '')}")

        cl_rx = self.fetch_final_cl_prescriptions(exam_id)
        if cl_rx:
            output.append("")  # Blank line for spacing
            output.append("=== Final Contact Lens Prescription ===")
            output.append("       Sphere  Cylinder  Axis  Add  BC   Dia   Manufacturer      Lens Type       Tint")
            for row in cl_rx:
                output.append("OD:   {0:<7} {1:<9} {2:<5} {3:<5} {4:<4} {5:<5} {6:<16} {7:<15} {8}".format(
                    row[0] or '', row[1] or '', row[2] or '', row[3] or '',
                    row[8] or '', row[9] or '', row[10] or '', row[11] or '', row[12] or ''
                ))
                output.append("OS:   {0:<7} {1:<9} {2:<5} {3:<5} {4:<4} {5:<5} {6:<16} {7:<15} {8}".format(
                    row[4] or '', row[5] or '', row[6] or '', row[7] or '',
                    row[13] or '', row[14] or '', row[15] or '', row[16] or '', row[17] or ''
                ))
                if row[18] or row[19]:
                    output.append(f"Expiration: {row[18] or ''}")
                    output.append(f"Comments: {row[19] or ''}")

        obj = self.fetch_objective_refraction(exam_id)
        if obj:
            output.append("")  # Blank line for spacing
            output.append("=== Objective Refraction - Autorefraction PD(mm): ===")        
            output.append(f"Instrument Used: {obj[0] or ''}")
            output.append("Sphere  Cylinder  Axis  Add  V Prism  Base  H Prism  Base  Acuity  Dist PD  Near PD")
            output.append("OD:      {0:<8}{1:<10}{2:<6}{3:<6}".format(obj[2] or '', obj[3] or '', obj[4] or '', obj[5] or ''))
            output.append("OS:      {0:<8}{1:<10}{2:<6}{3:<6}".format(obj[6] or '', obj[7] or '', obj[8] or '', obj[9] or ''))
            output.append(f"OU:      {obj[10] or ''}")
            output.append(f"PD(mm):  {obj[1] or ''}")
            if obj[11]:
                output.append(f"Comments: {obj[11]}")

        # Retinoscopy
        output.append("")
        output.append("=== Retinoscopy ===")
        output.append(f"Instrument Used: {ret.get('instrument', '')}   PD(mm): {ret.get('pd', '')}")
        output.append(f"OD: Sphere: {ret.get('sphere_od', '')}  Cylinder: {ret.get('cylinder_od', '')}  Axis: {ret.get('axis_od', '')}  Add: {ret.get('add_od', '')}")
        output.append(f"OS: Sphere: {ret.get('sphere_os', '')}  Cylinder: {ret.get('cylinder_os', '')}  Axis: {ret.get('axis_os', '')}  Add: {ret.get('add_os', '')}")
        output.append(f"OU: Acuity: {ret.get('dist_acuity_ou', '')}")

        # Subjective Refraction
        output.append("")
        output.append("=== Subjective Refraction ===")
        output.append("       Sphere   Cylinder  Axis   Add   Dist Acuity")
        output.append(f"Instrument Used: {subj.get('instrument', '')}")
        output.append(f"OD: Sphere: {subj.get('sphere_od', '')}  Cylinder: {subj.get('cylinder_od', '')}  Axis: {subj.get('axis_od', '')}  Add: {subj.get('add_od', '')}  Dist Acuity: {subj.get('dist_acuity_od', '')}")
        output.append(f"OS: Sphere: {subj.get('sphere_os', '')}  Cylinder: {subj.get('cylinder_os', '')}  Axis: {subj.get('axis_os', '')}  Add: {subj.get('add_os', '')}  Dist Acuity: {subj.get('dist_acuity_os', '')}")
        output.append(f"OU: Dist Acuity: {subj.get('dist_acuity_ou', '')}  Near Acuity: {subj.get('near_acuity_ou', '')}")

        # Cycloplegic Refraction
        output.append("")
        output.append("=== Cycloplegic Refraction ===")
        output.append(f"OD: Sphere: {cyclo.get('sphere_od', '')}  Cylinder: {cyclo.get('cylinder_od', '')}  Axis: {cyclo.get('axis_od', '')}  Add: {cyclo.get('add_od', '')}")
        output.append(f"OS: Sphere: {cyclo.get('sphere_os', '')}  Cylinder: {cyclo.get('cylinder_os', '')}  Axis: {cyclo.get('axis_os', '')}  Add: {cyclo.get('add_os', '')}")
        output.append(f"OU: Acuity: {cyclo.get('dist_acuity_ou', '')}")

        np = self.fetch_near_point_testing(exam_id)

        output.append("")  # Blank line for spacing
        output.append("=== Near Point Testing ===") 
        output.append(f"Dist Phoria: Horiz: {np['dist_phoria_h']}  Vert: {np['dist_phoria_v']}")
        output.append(f"Dist Vergence: BI: {np['dist_bi']}  BO: {np['dist_bo']}")
        output.append(f"Near Phoria: Horiz: {np['near_phoria_h']}  Vert: {np['near_phoria_v']}")
        output.append(f"Near Vergence: BI: {np['near_bi']}  BO: {np['near_bo']}")
        output.append(f"Gradient AC/A ratio: {np['aca_gradient']}")
        output.append(f"Calculated AC/A ratio: {np['aca_calc']}")
        
        np = self.fetch_near_point_testing(exam_id)
        output.append("")  # Blank line for spacing
        output.append("Accommodation:")
        output.append(f"PRA: {np['pra']}  NRA: {np['nra']}  MEM OD: {np['mem_od']}  MEM OS: {np['mem_os']}")
        output.append("Binocular Accommodative Facility (BAF) / Vergence Facility Testing:")
        output.append(f"With: {np['baf_with']}  Slow With: {np['baf_slow_with']}")
        output.append(f"Push Up (Diopters): OD: {np['pushup_od']}  OS: {np['pushup_os']}  OU: {np['pushup_ou']}")

        output.append("")  # Blank line for spacing  
        output.append("=== Examination ===")
        output.append(f"Additional testing & notes: {exam_physical.get('additional_testing_notes', '')}")

        # Pupils Section
        output.append("\nPupils:")
        output.append(f"  OD: Dim: {exam_physical.get('pupils_dim_od', '')} mm, Bright: {exam_physical.get('pupils_bright_od', '')} mm, Direct: {exam_physical.get('pupils_direct_od', '')} mm, Shape: {exam_physical.get('pupils_shape_od_text', '')}, APD: {exam_physical.get('pupils_apd', '')}")
        output.append(f"  OS: Dim: {exam_physical.get('pupils_dim_os', '')} mm, Bright: {exam_physical.get('pupils_bright_os', '')} mm, Direct: {exam_physical.get('pupils_direct_os', '')} mm, Shape: {exam_physical.get('pupils_shape_os_text', '')}, APD: {exam_physical.get('pupils_apd', '')}")
        output.append(f"  Comments: {exam_physical.get('pupils_comments', '')}")

        # ✅ Ensure motility data is fetched
        motility = self.fetch_exam_motility(exam_id) or {}

        output.append("\nMotility:")

        # ✅ Cover Test
        cover_test = motility.get('cover_test') or ''
        output.append(f"  Cover Test: {cover_test}")

        # ✅ Distance Line
        dist_a = motility.get('dist_a') or ''
        dist_hyper = "✓" if motility.get('dist_hyper') else " "
        dist_amt = motility.get('dist_amt') or ''
        output.append(f"  Dist: {dist_a}   hyper [{dist_hyper}]   tropia {dist_amt}")

        # ✅ Near Line
        near_a = motility.get('near_a') or ''
        near_hyper = "✓" if motility.get('near_hyper') else " "
        near_amt = motility.get('near_amt') or ''
        output.append(f"  Near: {near_a}   hyper [{near_hyper}]   tropia {near_amt}")

        # ✅ EOM Section with checkmarks
        output.append("  EOM: [{}] Full Range of Motion OU  [{}] Smooth  [{}] Choppy  [{}] Head Movement  [{}] Limited".format(
            "✓" if motility.get('eom_full_range') else " ",
            "✓" if motility.get('eom_smooth') else " ",
            "✓" if motility.get('eom_choppy') else " ",
            "✓" if motility.get('eom_head_mov') else " ",
            "✓" if motility.get('eom_limited') else " "
        ))

        # ✅ Comments with nice wrapping & indentation
        comments = motility.get('comment') or ''
        wrapped_comments = textwrap.fill(
            comments,
            width=80,                      # keep it consistent with rest of report
            initial_indent='  Comments: ', # starts with "Comments:"
            subsequent_indent=' ' * 12     # align wrapped lines under comment text
        )
        output.append(wrapped_comments)

        exam_confrontation = self.fetch_exam_confrontation(exam_id) or {}
        output.append("\nConfrontation:")
        output.append("  Confrontational Fields")
        output.append(f"  {exam_confrontation.get('ftfc_text', '')}")

        # Pull FTFC Type (ensure it's clean)
        ftfc_value = exam_confrontation.get('ftfc_type')
        if ftfc_value and ftfc_value.strip():   # only print if not None/empty
            output.append(f"  {ftfc_value}")

        # adnexae & Slit Lamp
        exam_slit = self.fetch_exam_slit_lamp(exam_id) or {}
        output.append("\nAdnexae:")

        # --- OD Section ---
        output.append("  OD")
        output.append(f"    Lids: {exam_slit.get('adnexae_lids_od_text', '')}")
        output.append(f"    Lashes: {exam_slit.get('adnexae_lashes_od_text', '')}")
        output.append(f"    Puncta: {exam_slit.get('adnexae_puncta_od_text', '')}")
        output.append(f"    Lacrimal Glands: {exam_slit.get('adnexae_lacrimal_od_text', '')}")
        output.append(f"    Orbits: {exam_slit.get('adnexae_orbits_od_text', '')}")
        output.append(f"    Preauricular Nodes: {exam_slit.get('adnexae_nodes_od_text', '')}")

        # --- OS Section ---
        output.append("  OS")
        output.append(f"    Lids: {exam_slit.get('adnexae_lids_os_text', '')}")
        output.append(f"    Lashes: {exam_slit.get('adnexae_lashes_os_text', '')}")
        output.append(f"    Puncta: {exam_slit.get('adnexae_puncta_os_text', '')}")
        output.append(f"    Lacrimal Glands: {exam_slit.get('adnexae_lacrimal_os_text', '')}")
        output.append(f"    Orbits: {exam_slit.get('adnexae_orbits_os_text', '')}")
        output.append(f"    Preauricular Nodes: {exam_slit.get('adnexae_nodes_os_text', '')}")

        # --- ANGLE SECTION ---
        output.append("\nAngle:")

        #  -- mapping dictionary for numeric codes to descriptive text
        angle_map = {
            "1": "I (closed)",
            "2": "II (narrow)",
            "3": "III (open)",
            "4": "IV (wide-open)"
        }

        #  -- map OD / OS numeric values to text
        od_angle = angle_map.get(str(exam_slit.get('angle_od', '')), exam_slit.get('angle_od', ''))
        os_angle = angle_map.get(str(exam_slit.get('angle_os', '')), exam_slit.get('angle_os', ''))

        #  -- print lines
        output.append(f"  OD   {od_angle}")
        output.append(f"  OS   {os_angle}")
        output.append(f"  Method: {exam_slit.get('angle_method_text', '')}")

        #  -- only print comments if they exist
        if exam_slit.get('angle_comment_text'):
            output.append(f"  Comments: {exam_slit.get('angle_comment_text', '')}")


        output.append("\nAnterior Chamber:")

        # --- OD Section ---
        output.append("  OD")
        output.append(f"    Depth: {exam_slit.get('ant_chamber_depth_od', '')}")
        output.append(f"    [{'✓' if exam_slit.get('ant_chamber_clear_od') else ' '}] Clear")
        output.append(f"    [{'✓' if exam_slit.get('ant_chamber_cell_od') else ' '}] Cell")
        output.append(f"    [{'✓' if exam_slit.get('ant_chamber_flare_od') else ' '}] Flare")

        # --- OS Section ---
        output.append("  OS")
        output.append(f"    Depth: {exam_slit.get('ant_chamber_depth_os', '')}")
        output.append(f"    [{'✓' if exam_slit.get('ant_chamber_clear_os') else ' '}] Clear")
        output.append(f"    [{'✓' if exam_slit.get('ant_chamber_cell_os') else ' '}] Cell")
        output.append(f"    [{'✓' if exam_slit.get('ant_chamber_flare_os') else ' '}] Flare")


        output.append("\nConjunctiva:")

        # --- OD Section ---
        output.append("  OD")
        output.append(f"    Palp Conj: {exam_slit.get('conjunctiva_pc_od_text', '')}")
        output.append(f"    Bulb Conj: {exam_slit.get('conjunctiva_bc_od_text', '')}")

        # --- OS Section ---
        output.append("  OS")
        output.append(f"    Palp Conj: {exam_slit.get('conjunctiva_pc_os_text', '')}")
        output.append(f"    Bulb Conj: {exam_slit.get('conjunctiva_bc_bos_text', '')}")

        output.append("\nCornea:")

        # --- OD Section ---
        output.append("  OD")
        output.append(f"    Epith: {'✓' if exam_slit.get('cornea_epith_od') else ''} {exam_slit.get('cornea_epith_od_text', '')}")
        output.append(f"    Stroma: {'✓' if exam_slit.get('cornea_stroma_od') else ''} {exam_slit.get('cornea_stroma_od_text', '')}")
        output.append(f"    Endoth: {'✓' if exam_slit.get('cornea_endoth_od') else ''} {exam_slit.get('cornea_endoth_od_text', '')}")
        output.append(f"    Tears: {'✓' if exam_slit.get('cornea_tears_od') else ''} {exam_slit.get('cornea_tears_od_text', '')}")

        # --- OS Section ---
        output.append("  OS")
        output.append(f"    Epith: {'✓' if exam_slit.get('cornea_epith_os') else ''} {exam_slit.get('cornea_epith_os_text', '')}")
        output.append(f"    Stroma: {'✓' if exam_slit.get('cornea_stroma_os') else ''} {exam_slit.get('cornea_stroma_os_text', '')}")
        output.append(f"    Endoth: {'✓' if exam_slit.get('cornea_endoth_os') else ''} {exam_slit.get('cornea_endoth_os_text', '')}")
        output.append(f"    Tears: {'✓' if exam_slit.get('cornea_tears_os') else ''} {exam_slit.get('cornea_tears_os_text', '')}")


        # Gonioscopy Section
        gonio = self.fetch_exam_gonioscopy(exam_id) or {}
        output.append("")
        output.append("Gonioscopy:")
        output.append(f"  OD Open to 360°: {'✓' if gonio.get('od_360') else ''}")
        output.append(f"  OS Open to 360°: {'✓' if gonio.get('os_360') else ''}")
        output.append("  Quadrants (OD / OS):")
        for quad in ['st', 'sn', 'it', 'in']:
            od_open = gonio.get(f"{quad}_od_open")
            od_narrow = gonio.get(f"{quad}_od_narrow")
            os_open = gonio.get(f"{quad}_os_open")
            os_narrow = gonio.get(f"{quad}_os_narrow")
            output.append(
                f"    {quad.upper():<3}: OD Open {'✓' if od_open else ''}  Narrow {'✓' if od_narrow else ''}   "
                f"OS Open {'✓' if os_open else ''}  Narrow {'✓' if os_narrow else ''}"
            )

        # Iris Section
        output.append("\nIris:")
        output.append(f"  OD: Flat: {'✓' if exam_slit.get('pupil_iris_flat_od') else ''} {exam_slit.get('pupil_iris_ri_text_od', '')}")
        output.append(f"  OS: Flat: {'✓' if exam_slit.get('pupil_iris_flat_os') else ''} {exam_slit.get('pupil_iris_ri_text_os', '')}")

        # Lens Section
        exam_lens = self.fetch_exam_lens(exam_id) or {}
        output.append("\nLens:")
        output.append(f"  OD: Clear {'✓' if exam_lens.get('lens_clear_od') else ''}, "
                    f"NS {'✓' if exam_lens.get('lens_ns_od') else ''}, "
                    f"Cort {'✓' if exam_lens.get('lens_cort_od') else ''}, "
                    f"PSC {'✓' if exam_lens.get('lens_psc_od') else ''}, "
                    f"Aphakic {'✓' if exam_lens.get('lens_aphakic_od') else ''}")
        output.append(f"     IOL Location: {exam_lens.get('iol_location_od', '')}")
        output.append(f"  OS: Clear {'✓' if exam_lens.get('lens_clear_os') else ''}, "
                    f"NS {'✓' if exam_lens.get('lens_ns_os') else ''}, "
                    f"Cort {'✓' if exam_lens.get('lens_cort_os') else ''}, "
                    f"PSC {'✓' if exam_lens.get('lens_psc_os') else ''}, "
                    f"Aphakic {'✓' if exam_lens.get('lens_aphakic_os') else ''}")
        output.append(f"     IOL Location: {exam_lens.get('iol_location_os', '')}")

        # Diagnostic Pharmaceuticals Section
        exam_pharma = self.fetch_exam_pharmaceutical(exam_id) or {}
        output.append("\nDiagnostic Pharmaceuticals:")

        # Header row (like PDF)
        output.append(f"  {'Dilation':<10} {'Pharmaceutical':<20} {'Concentration':<15} {'Other Dx Drugs':<20}")

        # OU first (per client PDF)
        output.append(f"  {'OU':<10} "
                    f"{exam_pharma.get('pharmaceutical_ou', ''):<20} "
                    f"{exam_pharma.get('concentration_ou', ''):<15} "
                    f"{exam_pharma.get('other_dx_drugs_ou', ''):<20}")

        # OD next
        output.append(f"  {'OD':<10} "
                    f"{exam_pharma.get('pharmaceutical_od', ''):<20} "
                    f"{exam_pharma.get('concentration_od', ''):<15} "
                    f"{exam_pharma.get('other_dx_drugs_od', ''):<20}")

        # OS last
        output.append(f"  {'OS':<10} "
                    f"{exam_pharma.get('pharmaceutical_os', ''):<20} "
                    f"{exam_pharma.get('concentration_os', ''):<15} "
                    f"{exam_pharma.get('other_dx_drugs_os', ''):<20}")

        # Only print comment line if there’s data
        if exam_pharma.get('pharmaceutical_comment'):
            output.append(f"  Comment: {exam_pharma.get('pharmaceutical_comment', '')}")

        # Sclera Section
        output.append("")
        output.append("Sclera:")
        output.append(f"  OD: {'✓' if exam_slit.get('conjunctiva_sclera_od', False) else ''} {exam_slit.get('conjunctiva_sclera_od_text', '')}")
        output.append(f"  OS: {'✓' if exam_slit.get('conjunctiva_sclera_os', False) else ''} {exam_slit.get('conjunctiva_sclera_os_text', '')}")

        # Fundoscopy Section
        output.append("")
        output.append("Fundoscopy:")
        output.append(f"  Undilated - Direct: {'✓' if exam_slit.get('undilated_funduscopy_direct', False) else ''}, "
                    f"BIO: {'✓' if exam_slit.get('undilated_funduscopy_bio', False) else ''}")
        output.append(f"  Dilated - Direct: {'✓' if exam_slit.get('dilated_funduscopy_direct', False) else ''}, "
                    f"BIO: {'✓' if exam_slit.get('dilated_funduscopy_bio', False) else ''}, "
                    f"VOLK-SLE: {'✓' if exam_slit.get('dilated_funduscopy_volk_sle', False) else ''}")
        output.append(f"  Other: {exam_slit.get('dilated_funduscopy_other_text', '')}")

        # Posterior Segment
        posterior = self.fetch_exam_posterior_segment(exam_id) or {}
        output.append("\nPosterior Segment:")
        output.append("  OD:")
        output.append(f"    Vitreous: {'Clear' if posterior.get('vitreous_od_clear') else ''} {'PVD' if posterior.get('vitreous_od_pvd') else ''} {'Floaters' if posterior.get('vitreous_od_floaters') else ''} {posterior.get('vitreous_od_comments', '')}")
        output.append(f"    Macula: {'Clear' if posterior.get('macula_clear_od') else ''} {'RPE' if posterior.get('macula_rpe_od') else ''} {'Drusen' if posterior.get('macula_drusen_od') else ''} {posterior.get('macula_od_other_text', '')}")
        output.append("  OS:")
        output.append(f"    Vitreous: {'Clear' if posterior.get('vitreous_os_clear') else ''} {'PVD' if posterior.get('vitreous_os_pvd') else ''} {'Floaters' if posterior.get('vitreous_os_floaters') else ''} {posterior.get('vitreous_os_comments', '')}")
        output.append(f"    Macula: {'Clear' if posterior.get('macula_clear_os') else ''} {'RPE' if posterior.get('macula_rpe_os') else ''} {'Drusen' if posterior.get('macula_drusen_os') else ''} {posterior.get('macula_os_other_text', '')}")
        output.append(f"  Comments: {posterior.get('comments', '')}")

        # Disc Assessment
        disc = self.fetch_exam_disc_assessment(exam_id) or {}
        output.append("\nDisc Assessment:")
        output.append("  OD:")
        output.append(f"    C/D Ratio: Horizontal = {disc.get('cd_ratio_h_od', '')}  Vertical = {disc.get('cd_ratio_v_od', '')}")
        output.append(f"    Disc Margins: {disc.get('margin_dist_od', '')}")
        output.append(f"    Appearance: {disc.get('appearance_od', '')}")
        output.append(f"    Neural Rim: {disc.get('neural_rim_od', '')}")
        output.append(f"    Nerve Fiber Layer: {disc.get('nerve_fiber_od', '')}")
        output.append(f"    Nerve Size: {disc.get('nerve_size_od', '')}")
        output.append(f"    Nerve Color: {disc.get('nerve_color_od', '')}")
        output.append("  OS:")
        output.append(f"    C/D Ratio: Horizontal = {disc.get('cd_ratio_h_os', '')}  Vertical = {disc.get('cd_ratio_v_os', '')}")
        output.append(f"    Disc Margins: {disc.get('margin_dist_os', '')}")
        output.append(f"    Appearance: {disc.get('appearance_os', '')}")
        output.append(f"    Neural Rim: {disc.get('neural_rim_os', '')}")
        output.append(f"    Nerve Fiber Layer: {disc.get('nerve_fiber_os', '')}")
        output.append(f"    Nerve Size: {disc.get('nerve_size_os', '')}")
        output.append(f"    Nerve Color: {disc.get('nerve_color_os', '')}")
        output.append(f"  Comments: {disc.get('comments', '')}")

        # Visual Fields
        output.append("\nVisual Fields:")
        method = ", ".join(str(v) for v in [exam_physical.get('visual_fields_method_cf'), exam_physical.get('visual_fields_method_auto')] if v)
        output.append(f"  Method: {method or 'None'}")
        output.append("  OD:")
        output.append(f"    SuperoTemporal: {'✓' if exam_physical.get('supero_temporal') else ''} {exam_physical.get('supero_temporal_text', '')}")
        output.append(f"    SuperoNasal: {'✓' if exam_physical.get('supero_nasal') else ''} {exam_physical.get('supero_nasal_text', '')}")
        output.append("  OS:")
        output.append(f"    SuperoTemporal: {'✓' if exam_physical.get('supero_os_temporal') else ''} {exam_physical.get('supero_os_temporal_text', '')}")
        output.append(f"    SuperoNasal: {'✓' if exam_physical.get('supero_os_nasal') else ''} {exam_physical.get('supero_os_nasal_text', '')}")
        if exam_slit.get('vf_comment_text'):
            output.append(f"  Comments: {exam_physical.get('vf_comment_text', '')}")

        coding = self.fetch_exam_coding(exam_id)
        output.append("")
        output.append("=== Coding ===")
        output.append(f"Diagnosis Code: {coding['dx_code']} - {coding['dx_desc']} | "
                      f"CPT1: {coding['cpt1']['code']} ({coding['cpt1']['desc']}) | "
                      f"CPT2: {coding['cpt2']['code']} ({coding['cpt2']['desc']})")
        # Wrap Description
        desc_label = "Description:"
        primary_desc = coding['cpt1']['desc'] or ''
        wrapped_primary = textwrap.wrap(primary_desc, width=80 - len(desc_label) - 1)
        if wrapped_primary:
            output.append(f"{desc_label} {wrapped_primary[0]}")
            for line in wrapped_primary[1:]:
                output.append(" " * (len(desc_label) + 1) + line)
        else:
            output.append(f"{desc_label}")
        output.append("Additional CPT Code:")
        output.append(f"Code: {coding['cpt2']['code']}")
        output.append(f"Related Diagnosis: {coding['cpt2']['dx']}")
        output.append(f"System: {coding['cpt2'].get('sys', '')}")
        output.append(f"Modifiers: {coding['cpt2']['mod']}")
        # Wrap Description
        additional_desc = coding['cpt2']['desc'] or ''
        wrapped_additional = textwrap.wrap(additional_desc, width=80 - len(desc_label) - 1)
        if wrapped_additional:
            output.append(f"{desc_label} {wrapped_additional[0]}")
            for line in wrapped_additional[1:]:
                output.append(" " * (len(desc_label) + 1) + line)
        else:
            output.append(f"{desc_label}")
        output.append("Provider Signature:")
        output.append("Electronically signed by Dr. Scott Earle")

        edu = self.fetch_final_education(exam_id)
        output.append("")  # Blank line for spacing
        output.append("=== Final Education ===")

        output.append("Next Visit:")

        val = edu.get('letter_to_md')
        output.append(f"Letter sent to MD: {val}" if val else "Letter sent to MD:")

        val = edu.get('ref_letter')
        output.append(f"Letter sent to referring doctor: {val}" if val else "Letter sent to referring doctor:")

        output.append(f"Discussed: {'✓' if edu.get('edu_discussed') else ''}")
        output.append(f"Told side effects of dilation: {'✓' if edu.get('edu_dilation') else ''}")
        output.append(f"Patient / parent told of plan: {'✓' if edu.get('edu_plan') else ''}")
        output.append(f"Patient to return for follow up: {edu['edu_return']}" if edu.get('edu_return') else "Patient to return for follow up:")
        output.append(f"Given MydSpecs: {'✓' if edu.get('edu_mydspecs') else ''}")
        output.append(f"Provider Signature: {edu['provider_signature']}" if edu.get('provider_signature') else "Provider Signature:")
        output.append(f"Date: {edu['signature_date']}" if edu.get('signature_date') else "Date:")

        output.append("")  # Blank line for spacing
        output.append("--- End of EHR Documentation ---\n")

        # Output final preview to the Tkinter text box
        self.preview_text.insert(tk.END, "\n".join(output))

    def fetch_pfsh_data(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    pfsh_past_ocular_glc,
                    pfsh_past_ocular_cat,
                    pfsh_past_ocular_dr,
                    pfsh_past_ocular_amd,
                    pfsh_past_ocular_ca,
                    pfsh_past_ocular_surgery,
                    pfsh_past_medical_htn,
                    pfsh_past_medical_chol,
                    pfsh_past_medical_dm,
                    pfsh_past_medical_other_text,
                    pfsh_family_ocular_glc,
                    pfsh_family_ocular_cat,
                    pfsh_family_ocular_amd,
                    pfsh_family_medical_htn,
                    pfsh_family_medical_dm,
                    pfsh_family_medical_other_text
                FROM public.exam_case_history
                WHERE exam_id = %s
            """, (exam_id,))
            result = cur.fetchone()

        if not result:
            return {}

        keys = [
            "past_ocular_glc", "past_ocular_cat", "past_ocular_dr", "past_ocular_amd",
            "past_ocular_ca", "past_ocular_surgery", "past_medical_htn", "past_medical_chol",
            "past_medical_dm", "past_medical_other_text", "family_ocular_glc", "family_ocular_cat",
            "family_ocular_amd", "family_medical_htn", "family_medical_dm", "family_medical_other_text"
        ]

        return dict(zip(keys, result))


    def fetch_ros_flags(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    pfsh_past_ocular_dr,
                    pfsh_past_ocular_ca,
                    pfsh_past_medical_chol
                FROM public.exam_case_history
                WHERE exam_id = %s
            """, (exam_id,))
            result = cur.fetchone()

        if not result:
            return {}

        flags = {
            "Allergic/Immunologic": "Yes" if result[2] else "No",  # cholesterol as systemic issue
            "Eyes": "Yes" if result[0] or result[1] else "No",
            "Musculoskeletal": "No data",
            "Cardiovascular": "Yes" if result[2] else "No",
            "Gastrointestinal": "No data",
            "Neurological": "No data",
            "Constitutional": "No data",
            "Genitourinary": "No data",
            "Psychiatric": "No data",
            "Ears, Nose, Mouth & Throat": "No data",
            "Hematologic/Lymphatic": "No data",
            "Respiratory": "No data",
            "Endocrine": "No data",
            "Integumentary": "No data"
        }

        return flags

    def fetch_full_pretesting_data(self, exam_id):
        data = {}

        with self.conn.cursor() as cur:
            # Color Vision + Stereo
            cur.execute("""
                SELECT
                    color_vision_a_od, color_vision_test_od,
                    color_vision_a_os, color_vision_test_os,
                    stereo_arc_sec, stereo_test
                FROM exam_color_vision
                WHERE exam_id = %s
            """, (exam_id,))
            row = cur.fetchone()
            if row:
                data.update({
                    'cv_od': row[0], 'cv_test_od': row[1],
                    'cv_os': row[2], 'cv_test_os': row[3],
                    'stereo_score': row[4], 'stereo_test': row[5]
                })

            # Corneal Topography
            cur.execute("""
                SELECT
                    od_h_diopters, od_h_axis, od_v_diopters, od_v_axis,
                    os_h_diopters, os_h_axis, os_v_diopters, os_v_axis
                FROM exam_cornea_topography
                WHERE exam_id = %s
            """, (exam_id,))
            row = cur.fetchone()
            if row:
                data.update({
                    'ct_od_h_d': row[0], 'ct_od_h_ax': row[1],
                    'ct_od_v_d': row[2], 'ct_od_v_ax': row[3],
                    'ct_os_h_d': row[4], 'ct_os_h_ax': row[5],
                    'ct_os_v_d': row[6], 'ct_os_v_ax': row[7]
                })

            # Keratometry
            cur.execute("""
                SELECT
                    od_h_diopters, od_h_axis, od_v_diopters, od_v_axis, od_mires,
                    os_h_diopters, os_h_axis, os_v_diopters, os_v_axis, os_mires
                FROM exam_keratometry
                WHERE exam_id = %s
            """, (exam_id,))
            row = cur.fetchone()
            if row:
                data.update({
                    'k_od_h_d': row[0], 'k_od_h_ax': row[1],
                    'k_od_v_d': row[2], 'k_od_v_ax': row[3], 'k_od_mires': row[4],
                    'k_os_h_d': row[5], 'k_os_h_ax': row[6],
                    'k_os_v_d': row[7], 'k_os_v_ax': row[8], 'k_os_mires': row[9]
                })

        # Tonometry placeholder
        # Tonometry
            cur.execute("""
                SELECT od, os, eye_drop, eye_drop_eye, method
                FROM exam_tonometry
                WHERE exam_id = %s
            """, (exam_id,))
            row = cur.fetchone()
            if row:
                data.update({
                    'tono_od': row[0], 'tono_os': row[1],
                    'tono_eye_drop': row[2],
                    'tono_oculus': row[3],
                    'tono_method': row[4]
                })

                return data

    def fetch_visual_acuity_and_vitals(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    va_unaided_od, va_unaided_os, va_unaided_ou,
                    va_od_aided_dist, va_od_aided_16, va_od_aided_pinhole,
                    va_os_aided_dist, va_os_aided_16, va_os_aided_pinhole,
                    va_ou_aided_dist, va_ou_aided_16, va_ou_aided_pinhole,
                    height, weight,
                    blood_pressure_a, blood_pressure_b,
                    blood_pressure_sugar, a1c,
                    heart_rate, body_temperature, respiratory_rate
                FROM exam_physical
                WHERE exam_id = %s
            """, (exam_id,))
            row = cur.fetchone()

        keys = [
            'unaided_od', 'unaided_os', 'unaided_ou',
            'aided_od_dist', 'aided_od_16', 'aided_od_pinhole',
            'aided_os_dist', 'aided_os_16', 'aided_os_pinhole',
            'aided_ou_dist', 'aided_ou_16', 'aided_ou_pinhole',
            'height', 'weight',
            'bp_a', 'bp_b',
            'blood_sugar', 'a1c',
            'heart_rate', 'temperature', 'resp_rate'
        ]

        return dict(zip(keys, row)) if row else {k: "<missing>" for k in keys}

    def fetch_spec_prescriptions(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    sp.ordinal,
                    sp.sphere_od, sp.cylinder_od, sp.axis_od, sp.add_od,
                    sp.sphere_os, sp.cylinder_os, sp.axis_os, sp.add_os,
                    sp.acuity_od AS dist_acuity_od,
                    sp.acuity_os AS dist_acuity_os,
                    sp.acuity_ou AS dist_acuity_ou,
                    ehs.near_acuity_od,
                    ehs.near_acuity_os,
                    ehs.near_acuity_ou,
                    sp.expiration_date,
                    sp.recommendation
                FROM spec_prescription sp
                LEFT JOIN exam_habitual_spec ehs ON sp.exam_id = ehs.exam_id
                WHERE sp.exam_id = %s
                ORDER BY sp.ordinal;
            """, (exam_id,))
            results = cur.fetchall()

        data = {}

        if not results:
            print(f"[DEBUG] No records found for exam_id: {exam_id}")
            return data  # This stops execution here if empty

        for row in results:

            ord_num = row[0]
            data[ord_num] = {
                    'sphere_od': row[1] or 'X',
                    'cylinder_od': row[2] or 'X',
                    'axis_od': row[3] or 'X',
                    'add_od': row[4] or 'X',
                    'sphere_os': row[5] or 'X',
                    'cylinder_os': row[6] or 'X',
                    'axis_os': row[7] or 'X',
                    'add_os': row[8] or 'X',
                    'dist_acuity_od': row[9] or '',
                    'dist_acuity_os': row[10] or '',
                    'dist_acuity_ou': row[11] or '',
                    'near_acuity_od': row[12] or '',
                    'near_acuity_os': row[13] or '',
                    'near_acuity_ou': row[14] or '',
                    'expiration': row[15].strftime('%m/%d/%Y') if isinstance(row[15], (datetime, date)) else (row[15] or ''),
                    'recommend': row[16] or ''
                }

        return data

    def format_spectacle_line(eye, values):
        return f"{eye:<5} {values['Sphere']:<8} {values['Cylinder']:<9} {values['Axis']:<6} {values['Add']:<6} " \
            f"{values['VPrism']:<8} {values['BaseV']:<6} {values['HPrism']:<8} {values['BaseH']:<6} " \
            f"{values['DistAcuity']:<13} {values['NearAcuity']}"
  
    def fetch_contact_lens_prescriptions(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    ordinal,
                    sphere_od, cylinder_od, axis_od, add_od,
                    sphere_os, cylinder_os, axis_os, add_os,
                    acuity_ou, near_acuity_ou,
                    tint_od, tint_os
                FROM cl_prescription
                WHERE exam_id = %s
                ORDER BY ordinal
            """, (exam_id,))
            return cur.fetchall()

    def fetch_autorefraction(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    sphere_od, cylinder_od, axis_od, add_od,
                    sphere_os, cylinder_os, axis_os, add_os,
                    acuity_ou
                FROM spec_prescription
                WHERE exam_id = %s AND ordinal = 2
                LIMIT 1
            """, (exam_id,))
            row = cur.fetchone()

        if not row:
            return {
                'instrument': '<AR_INSTRUMENT>', 'pd': '<AR_PD>',
                'od_sph': '<AR_OD_SPH>', 'od_cyl': '<AR_OD_CYL>', 'od_axis': '<AR_OD_AXIS>', 'od_add': '<AR_OD_ADD>',
                'os_sph': '<AR_OS_SPH>', 'os_cyl': '<AR_OS_CYL>', 'os_axis': '<AR_OS_AXIS>', 'os_add': '<AR_OS_ADD>',
                'ou_acuity': '<AR_OU_ACUITY>'
            }

        return {
            'instrument': 'Autorefractor',
            'pd': '63',
            'od_sph': row[0], 'od_cyl': row[1], 'od_axis': row[2], 'od_add': row[3],
            'os_sph': row[4], 'os_cyl': row[5], 'os_axis': row[6], 'os_add': row[7],
            'ou_acuity': row[8]
        }

    def fetch_retinoscopy(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    sphere_od, cylinder_od, axis_od, add_od,
                    sphere_os, cylinder_os, axis_os, add_os,
                    acuity_ou
                FROM exam_habitual_spec
                WHERE exam_id = %s
                LIMIT 1
            """, (exam_id,))
            row = cur.fetchone()

        if not row:
            return {
                'instrument': 'Retinoscope',
                'pd': '<RETINOSCOPY_PD>',
                'od_sph': '<RET_OD_SPH>', 'od_cyl': '<RET_OD_CYL>',
                'od_axis': '<RET_OD_AXIS>', 'od_add': '<RET_OD_ADD>',
                'os_sph': '<RET_OS_SPH>', 'os_cyl': '<RET_OS_CYL>',
                'os_axis': '<RET_OS_AXIS>', 'os_add': '<RET_OS_ADD>',
                'ou_acuity': '<RET_OU_ACUITY>'
            }

        return {
            'instrument': 'Retinoscope',
            'pd': '63',
            'od_sph': row[0], 'od_cyl': row[1],
            'od_axis': row[2], 'od_add': row[3],
            'os_sph': row[4], 'os_cyl': row[5],
            'os_axis': row[6], 'os_add': row[7],
            'ou_acuity': row[8]
        }

    def fetch_subjective_refraction(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    ordinal,
                    sphere_od, cylinder_od, axis_od, add_od,
                    sphere_os, cylinder_os, axis_os, add_os,
                    acuity_ou
                FROM spec_prescription
                WHERE exam_id = %s
            """, (exam_id,))
            rows = cur.fetchall()

        result = {}
        for row in rows:
            ordinal = row[0]
            data = {
                'od_sph': row[1], 'od_cyl': row[2], 'od_axis': row[3], 'od_add': row[4],
                'os_sph': row[5], 'os_cyl': row[6], 'os_axis': row[7], 'os_add': row[8],
                'ou_acuity': row[9]
            }
            if ordinal == 1:
                result.update({
                    'instrument': 'N/A',
                    'od_sph': data['od_sph'], 'od_cyl': data['od_cyl'], 'od_axis': data['od_axis'], 'od_add': data['od_add'],
                    'os_sph': data['os_sph'], 'os_cyl': data['os_cyl'], 'os_axis': data['os_axis'], 'os_add': data['os_add'],
                    'ou_dist_acuity': data['ou_acuity'], 'ou_near_acuity': ''
                })
        return result
        
    def fetch_cycloplegic_refraction(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    sphere_od, cylinder_od, axis_od, add_od,
                    sphere_os, cylinder_os, axis_os, add_os,
                    acuity_ou
                FROM exam_habitual_cl
                WHERE exam_id = %s
                LIMIT 1
            """, (exam_id,))
            row = cur.fetchone()

        if not row:
            return {
                'od_sph': '<CYC_OD_SPH>', 'od_cyl': '<CYC_OD_CYL>',
                'od_axis': '<CYC_OD_AXIS>', 'od_add': '<CYC_OD_ADD>',
                'os_sph': '<CYC_OS_SPH>', 'os_cyl': '<CYC_OS_CYL>',
                'os_axis': '<CYC_OS_AXIS>', 'os_add': '<CYC_OS_ADD>',
                'ou_acuity': '<CYC_OU_ACUITY>'
            }

        return {
            'od_sph': row[0], 'od_cyl': row[1], 'od_axis': row[2], 'od_add': row[3],
            'os_sph': row[4], 'os_cyl': row[5], 'os_axis': row[6], 'os_add': row[7],
            'ou_acuity': row[8]
        }
        
    def fetch_near_point_testing(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    dist_phoria_horiz,
                    dist_phoria_vert,
                    dist_vergence_bi_a,
                    dist_vergence_bo_a,
                    near_phoria_horiz,
                    near_phoria_vert,
                    near_vergence_bi_a,
                    near_vergence_bo_a,
                    grad_aca_a,
                    calc_aca_a,
                    pra_a,
                    nra_a,
                    mem_od,
                    mem_os,
                    baf_with,
                    baf_slow_with,
                    pu_od,
                    pu_os,
                    pu_ou
                FROM exam_near_point_testing
                WHERE exam_id = %s
                LIMIT 1
            """, (exam_id,))
            row = cur.fetchone()

        if not row:
            return {
                'dist_phoria_h': '<NP_DIST_PHORIA_H>',
                'dist_phoria_v': '<NP_DIST_PHORIA_V>',
                'dist_bi': '<NP_DIST_BI>',
                'dist_bo': '<NP_DIST_BO>',
                'near_phoria_h': '<NP_NEAR_PHORIA_H>',
                'near_phoria_v': '<NP_NEAR_PHORIA_V>',
                'near_bi': '<NP_NEAR_BI>',
                'near_bo': '<NP_NEAR_BO>',
                'aca_gradient': '<NP_ACA_GRADIENT>',
                'aca_calc': '<NP_ACA_CALC>',
                'pra': '<NP_PRA>',
                'nra': '<NP_NRA>',
                'mem_od': '<NP_MEM_OD>',
                'mem_os': '<NP_MEM_OS>',
                'baf_with': '<NP_BAF_WITH>',
                'baf_slow_with': '<NP_BAF_SLOW_WITH>',
                'pushup_od': '<NP_PUSHUP_OD>',
                'pushup_os': '<NP_PUSHUP_OS>',
                'pushup_ou': '<NP_PUSHUP_OU>'
            }

        keys = [
            'dist_phoria_h', 'dist_phoria_v',
            'dist_bi', 'dist_bo',
            'near_phoria_h', 'near_phoria_v',
            'near_bi', 'near_bo',
            'aca_gradient', 'aca_calc',
            'pra', 'nra',
            'mem_od', 'mem_os',
            'baf_with', 'baf_slow_with',
            'pushup_od', 'pushup_os', 'pushup_ou'
        ]
        return dict(zip(keys, row))

    def fetch_exam_npc(self, exam_id):
        return {
            'break': '<NPC_BREAK>', 'recovery': '<NPC_RECOVERY>', 'target': '<NPC_TARGET>'
        }

    def fetch_exam_confrontation(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT ftfc_type
                FROM exam_confrontation
                WHERE exam_id = %s
            """, (exam_id,))
            row = cur.fetchone()
            if not row:
                return {'ftfc_text': ''}

            ftfc_type = row[0]

            # ✅ Map numeric DB values to text
            ftfc_map = {
                0: 'FTFC OD, OS',
                1: 'FTFC OD only',
                2: 'FTFC OS only',
                3: 'No FTFC'
            }

            ftfc_text = ftfc_map.get(ftfc_type, f"Unknown ({ftfc_type})")
            return {'ftfc_text': ftfc_text}

    def fetch_exam_fundus(self, exam_id):
        return {
            'dilated': {
                'bio': '<FUND_BIO>', 'direct': '<FUND_DIRECT>', 'volk': '<FUND_VOLK>'
            },
            'undilated': {
                'bio': '<UFUND_BIO>', 'direct': '<UFUND_DIRECT>', 'volk': '<UFUND_VOLK>'
            },
            'reappt': '<FUND_REAPPT>',
            'posterior': {
                'fund_od': '<POST_FUND_OD>', 'fund_os': '<POST_FUND_OS>',
                'me_od': '<POST_ME_OD>', 'me_os': '<POST_ME_OS>',
                'ret_od': '<POST_RET_OD>', 'ret_os': '<POST_RET_OS>',
                'fr_od': '<POST_FR_OD>', 'fr_os': '<POST_FR_OS>',
                'periph_od': '<POST_PERIPH_OD>', 'periph_os': '<POST_PERIPH_OS>',
                'vessel_od': '<POST_VESSEL_OD>', 'vessel_os': '<POST_VESSEL_OS>',
                'avr_od': '<POST_AVR_OD>', 'avr_os': '<POST_AVR_OS>',
                'vit_od': '<POST_VIT_OD>', 'vit_os': '<POST_VIT_OS>',
                'comments': '<POST_COMMENTS>'
            },
            'disc': {
                'cd_od': '<DISC_CD_OD>', 'cd_os': '<DISC_CD_OS>',
                'marg_od': '<DISC_MARG_OD>', 'marg_os': '<DISC_MARG_OS>',
                'app_od': '<DISC_APP_OD>', 'app_os': '<DISC_APP_OS>',
                'nr_od': '<DISC_NR_OD>', 'nr_os': '<DISC_NR_OS>',
                'nfl_od': '<DISC_NFL_OD>', 'nfl_os': '<DISC_NFL_OS>',
                'size_od': '<DISC_SIZE_OD>', 'size_os': '<DISC_SIZE_OS>',
                'color_od': '<DISC_COLOR_OD>', 'color_os': '<DISC_COLOR_OS>'
            }
        }
    
    def fetch_exam_coding(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT
                    e.id AS exam_id,
                    dcd.code AS icd10_code,
                    dcd.code_system,
                    emdc.id AS emdc_id,  -- 👈 this line added
                    emdc.procedure_code,
                    emdc.procedure_code_desc
                FROM exam e
                JOIN exam_medical_decision_code emdc ON e.id = emdc.exam_medical_decision_id
                JOIN exam_procedure_diagnosis_code_detail_xref xref ON xref.exam_procedure_id = emdc.id
                JOIN diagnosis_code_detail dcd ON dcd.id = xref.diagnosis_detail_id
                WHERE e.id = %s
                ORDER BY emdc.id
            """, (exam_id,))
            rows = cur.fetchall()  # <- named rows, not result

        if not rows:
            return {
                'dx_code': '<DX_CODE>',
                'dx_desc': '<DX_DESC>',
                'cpt1': {'code': '', 'dx': '', 'mod': '', 'desc': ''},
                'cpt2': {'code': '', 'dx': '', 'mod': '', 'desc': ''}
            }

        dx_code = rows[0][1]
        dx_desc = rows[0][4]

        cpts = []
        seen = set()
        for row in rows:
            icd10_code = row[1]
            cpt_code = row[3]
            cpt_desc = row[4]

            if (cpt_code, icd10_code) in seen:
                continue
            seen.add((cpt_code, icd10_code))

            cpts.append({
                'code': cpt_code,
                'dx': icd10_code,
                'mod': '',
                'desc': cpt_desc
            })
            if len(cpts) >= 2:
                break

        while len(cpts) < 2:
            cpts.append({'code': '', 'dx': '', 'mod': '', 'desc': ''})

        return {
            'dx_code': dx_code,
            'dx_desc': dx_desc,
            'cpt1': cpts[0],
            'cpt2': cpts[1]
        }
    
    def fetch_exam_posterior_segment(self, exam_id):
            """Fetch all posterior segment data for OD and OS, including macula fields."""
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        comments,
                        vitreous_od_clear, vitreous_od_pvd, vitreous_od_floaters, vitreous_od_comments,
                        vitreous_os_clear, vitreous_os_pvd, vitreous_os_floaters, vitreous_os_comments,
                        macula_clear_od, macula_clear_os,
                        macula_rpe_od, macula_rpe_os,
                        macula_drusen_od, macula_drusen_os,
                        macula_other_od, macula_other_os,
                        macula_od_other_text, macula_os_other_text,
                        macula_edema_od_id, macula_edema_os_id,
                        macula_edema_normal_od, macula_edema_normal_os
                    FROM exam_posterior_segment
                    WHERE exam_id = %s
                """, (exam_id,))
                row = cur.fetchone()
                if not row:
                    return {}
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, row))
            
    def fetch_exam_disc_assessment(self, exam_id):
        """Fetch disc assessment information for OD and OS (only real columns)."""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    comments,
                    appearance_abnormal_od, appearance_abnormal_os,
                    appearance_od, appearance_os,
                    cd_ratio_h_od, cd_ratio_h_os,
                    cd_ratio_v_od, cd_ratio_v_os,
                    margin_dist_od, margin_dist_os,
                    nerve_color_od, nerve_color_os,
                    nerve_fiber_normal_od, nerve_fiber_normal_os,
                    nerve_fiber_od, nerve_fiber_os,
                    nerve_size_od, nerve_size_os,
                    neural_rim_od, neural_rim_os
                FROM exam_disc_assessment
                WHERE exam_id = %s
            """, (exam_id,))
            row = cur.fetchone()
            if not row:
                return {}
            columns = [desc[0] for desc in cur.description]
            return dict(zip(columns, row))

    def fetch_final_education(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    NULL AS edu_md_letter,
                    NULL AS edu_ref_letter,
                    emd.education_discussed AS edu_discussed,
                    emd.education_dilation_side_effects AS edu_dilation,
                    emd.education_plan AS edu_plan,
                    NULL AS edu_return,
                    emd.education_mydspecs AS edu_mydspecs,
                    NULL AS provider_signature,
                    NULL AS signature_date
                FROM exam_medical_decision emd
                WHERE emd.exam_id = %s
                LIMIT 1
            """, (exam_id,))
            row = cur.fetchone()

        if not row:
            return {
                'md_letter': '<EDU_MD_LETTER>',
                'ref_letter': '<EDU_REF_LETTER>',
                'edu_discussed': '<EDU_DISCUSS>',
                'edu_dilation': '<EDU_DILATION>',
                'edu_plan': '<EDU_PLAN>',
                'edu_return': '<EDU_RETURN>',
                'edu_mydspecs': '<EDU_MYDSPECS>',
                'provider_signature': '<PROVIDER_SIGNATURE>',
                'signature_date': '<SIGNATURE_DATE>'
            }

        return {
            'md_letter': row[0],
            'ref_letter': row[1],
            'edu_discussed': row[2],
            'edu_dilation': row[3],
            'edu_plan': row[4],
            'edu_return': row[5],
            'edu_mydspecs': row[6],
            'provider_signature': row[7],
            'signature_date': row[8]
        }

    def generate_pdf(self):
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.colors import black, grey, Color, white
        from reportlab.lib.units import inch
        from tkinter import messagebox
        import os
        import textwrap

        exam_id = self.exam_var.get().strip()
        if not exam_id:
            messagebox.showwarning("No Exam Selected", "Please select an exam before generating PDF.")
            return

        output_dir = r"C:\Users\Randy\Documents\exam_notes_app\output"
        os.makedirs(output_dir, exist_ok=True)
        filename = os.path.join(output_dir, f"exam_{exam_id}_notes.pdf")

        try:
            raw_content = self.preview_text.get("1.0", tk.END).splitlines()
            content = list(raw_content)  # Use exactly what was previewed

            c = canvas.Canvas(filename, pagesize=letter)
            width, height = letter
            x_margin = 50
            y = height - 50

            c.setFont("Courier-Bold", 16)
            c.drawString(x_margin, y, f"Patient Exam Report - Exam ID {exam_id}")
            y -= 30

            c.setFont("Courier", 10)

            for line in content:
                if line.startswith("===") and line.endswith("==="):
                    if y < 50 + 13 * 10:
                        c.showPage()
                        y = height - 50
                        c.setFont("Courier", 10)

                    y -= 20
                    header_text = line.strip("= ").strip()
                    header_height = 16
                    rect_height = header_height + 6

                    c.setFillColor(Color(0.7, 0.7, 0.7))
                    c.rect(x_margin - 2, y - 2, width - 2 * x_margin + 4, rect_height, fill=True, stroke=False)

                    c.setFillColor(white)
                    c.setFont("Helvetica-Bold", 12)
                    text_y = y + (rect_height - 12) / 2  # 12 = font size
                    c.drawString(x_margin, text_y, header_text)
                    y -= (rect_height + 10)

                    c.setFillColor(black)
                    c.setFont("Courier", 10)
                else:
                    wrapped_lines = textwrap.wrap(line, width=100)
                    for wrapped_line in wrapped_lines:
                        c.drawString(x_margin, y, wrapped_line)
                        y -= 13
                        if y < 50:
                            c.showPage()
                            y = height - 50
                            c.setFont("Courier", 10)

            c.save()
            messagebox.showinfo("Success", f"PDF saved to:\n{filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate PDF:\n{e}")

    def fetch_exam_slit_lamp(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    -- 🔹 adnexae SECTION (OD & OS)
                    adnexae_lids_od, adnexae_lids_od_text,
                    adnexae_lashes_od, adnexae_lashes_od_text,
                    adnexae_punta_od, adnexae_puncta_od_text,
                    adnexae_orbits_od, adnexae_orbits_od_text,
                    adnexae_nodes_od, adnexae_nodes_od_text,
                    adnexae_lids_os, adnexae_lids_os_text,
                    adnexae_lashes_os, adnexae_lashes_os_text,
                    adnexae_puncta_os, adnexae_puncta_os_text,
                    adnexae_orbits_os, adnexae_orbits_os_text,
                    adnexae_nodes_os, adnexae_nodes_os_text,
                    adnexae_other_text,
                    -- 🔹 ANGLE
                    angle_od, angle_os, angle_comment_text, angle_method_text,
                    -- 🔹 ANTERIOR CHAMBER
                    ant_chamber_depth_od, ant_chamber_clear_od,
                    ant_chamber_depth_os, ant_chamber_clear_os,
                    -- 🔹 CONJUNCTIVA
                    conjunctiva_pc_od, conjunctiva_pc_od_text,
                    conjunctiva_pc_os, conjunctiva_pc_os_text,
                    conjunctiva_bc_od, conjunctiva_bc_od_text,
                    conjunctiva_bc_os, conjunctiva_bc_bos_text,   -- ✅ column is indeed `_bos_text`
                    conjunctiva_sclera_od, conjunctiva_sclera_od_text,
                    conjunctiva_sclera_os, conjunctiva_sclera_os_text,
                    -- 🔹 CORNEA
                    cornea_epith_od, cornea_epith_od_text,
                    cornea_stroma_od, cornea_stroma_od_text,
                    cornea_endoth_od, cornea_endoth_od_text,
                    cornea_tears_od, cornea_tears_od_text,
                    cornea_epith_os, cornea_epith_os_text,
                    cornea_stroma_os, cornea_stroma_os_text,
                    cornea_endoth_os, cornea_endoth_os_text,
                    cornea_tears_os, cornea_tears_os_text,
                    -- 🔹 GONIOSCOPY
                    gonioscopy_text,
                    -- 🔹 IRIS
                    pupil_iris_flat_od, pupil_iris_flat_os,
                    pupil_iris_ri_od, pupil_iris_ri_os,
                    pupil_iris_ri_text_od, pupil_iris_ri_text_os,
                    -- 🔹 FUNDOSCOPY
                    undilated_funduscopy_direct, undilated_funduscopy_bio,
                    dilated_funduscopy_direct, dilated_funduscopy_bio,
                    dilated_funduscopy_other, dilated_funduscopy_other_text,
                    -- 🔹 PHARMACEUTICALS
                    pharmaceutical_od, pharmaceutical_os, pharmaceutical_ou, pharmaceutical_comment
                FROM exam_slit
                WHERE exam_id = %s;
             """, (exam_id,))
            row = cur.fetchone()
            if not row:
                return {}
            columns = [desc[0] for desc in cur.description]
            data = dict(zip(columns, row))
            return data

    def fetch_exam_lens(self, exam_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    lens_clear_od,
                    lens_clear_os,
                    posterior_capsule_od,
                    posterior_capsule_od_value,
                    posterior_capsule_os,
                    posterior_capsule_os_value
                FROM exam_lens
                WHERE exam_id = %s
            """, (exam_id,))
            row = cur.fetchone()
            if row:
                keys = [
                    'lens_clear_od', 'lens_clear_os',
                    'posterior_capsule_od', 'posterior_capsule_od_value',
                    'posterior_capsule_os', 'posterior_capsule_os_value'
                ]
                return dict(zip(keys, row))
            return {key: '' for key in keys}


        if not row:
            return {}

        keys = [
            'lids_od', 'lashes_od', 'puncta_od',
            'lids_os', 'lashes_os', 'puncta_os',
            'adnexae_other',
            'angle_comment', 'angle_method', 'angle_od', 'angle_os',
            'ac_clear_od', 'ac_depth_od',
            'ac_clear_os', 'ac_depth_os',
            'conj_pc_od', 'conj_pc_os',
            'conj_bc_od', 'conj_bc_os',
            'cor_epith_od', 'cor_stroma_od', 'cor_endoth_od', 'cor_tears_od',
            'cor_epith_os', 'cor_stroma_os', 'cor_endoth_os', 'cor_tears_os',
            'iris_flat_od', 'iris_ri_od', 'iris_ri_text_od',
            'iris_flat_os', 'iris_ri_os', 'iris_ri_text_os',
            'lens_comment',
            'fund_bio_undil', 'fund_dir_undil', 'fund_volk_undil',
            'fund_bio_dil', 'fund_dir_dil', 'fund_volk_dil',
            'gonio_text'
        ]

        return dict(zip(keys, row))
if __name__ == '__main__':
    root = tk.Tk()
    root.title("Patient Exam Selector")
    root.state('zoomed')  # Maximize on Windows
    app = PatientExamSelector(root)
    app.mainloop()
