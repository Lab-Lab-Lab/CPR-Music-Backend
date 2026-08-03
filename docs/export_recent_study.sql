-- need to tunnel via ssm session port forwarding

select
	cc2.id as course_id, cc2."name" as course_name,uu3.username as teacher_name,
	uu2.id as student_user_id, uu2.grade, ce.id as course_enrollment_id, ce.course_id,
	ce.instrument_id, ce.role_id, aa.id as assn_id, aa.activity_id as act_id, aa2.activity_type_name, aa2.category, 
	aa.instrument_id as assn_instr_id, ii."name",ss.enrollment_id as subm_enrollmt_id, ss.part_id as subm_part_id,
	aa.piece_plan_id as assn_pplan_id, aa.piece_id as assn_piece_id, mp2."name" as piece_name, ss.id as sub_id,
	ss.course_assignment_id as sb_assn_id, ss.submitted as sub_dt, ss.content, ss2.*, sg.rhythm, sg.tone, sg."expression",
	uu4."name" as grader, sg2.rhythm self_rhythm, sg2.tone as self_tone, sg2."expression" as self_expression
from courses_enrollment ce
join courses_course cc2 on cc2.id=ce.course_id 
join users_user uu3 on uu3.id=cc2.owner_id 
join users_user uu2 on uu2.id=ce.user_id
left join assignments_courseassignment aa on aa.course_id =ce.course_id  
left join assignments_activity aa2 on aa2.id=aa.activity_id 
left join instruments_instrument ii on ii.id=aa.instrument_id 
left join submissions_submission ss on ss.enrollment_id=ce.id and ss.course_assignment_id=aa.id
left join musics_part mp on mp.id =ss.part_id 
left join musics_piece mp2 on mp2.id =mp.piece_id 
left join submissions_grade sg on ss.grade_id = sg.id 
left join users_user uu4 on uu4.id =sg.grader_id 
left join submissions_grade sg2 on sg2.id =ss.self_grade_id 
left join submissions_submissionattachment ss2 on ss2.submission_id =ss.id 
where ce.course_id in (
	select cc.id 
	from courses_course cc
	where cc.owner_id in (
		select uu.id from users_user uu where uu.username in ('demoalanna', 'charlyne', 'katie', 'holly')
	)
)