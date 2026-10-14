"""All review, evidence and report access is teacher-owned; no student routes."""
from fastapi import BackgroundTasks, Request
from fastapi.responses import FileResponse, Response

from .review import ReviewService
from .review_reports import ReviewReports
from .service import Problem


def install_review_routes(app,service,sync,owner):
    review=ReviewService(service,sync); reports=ReviewReports(review)
    app.state.review,app.state.reports=review,reports
    prefix='/api/v1'

    @app.get(prefix+'/attempts/{attempt_id}/review')
    def detail(request:Request,attempt_id:str):
        return review.detail(owner(request),attempt_id)

    @app.post(prefix+'/attempts/{attempt_id}/reviews')
    def decide(request:Request,attempt_id:str,data:dict):
        return review.review(owner(request,True),attempt_id,data)

    @app.post(prefix+'/attempts/{attempt_id}/manual')
    def manual(request:Request,attempt_id:str,data:dict):
        return review.manual(owner(request,True),attempt_id,data)

    @app.post(prefix+'/attempts/{attempt_id}/manual/{observation_id}')
    def correct_manual(request:Request,attempt_id:str,observation_id:str,data:dict):
        return review.manual(owner(request,True),attempt_id,data,observation_id)

    @app.post(prefix+'/attempts/{attempt_id}/conclusions',status_code=202)
    def conclude(request:Request,attempt_id:str,data:dict,tasks:BackgroundTasks):
        teacher=owner(request,True)
        version=review.conclude(teacher,attempt_id,data)
        tasks.add_task(reports.generate,teacher,attempt_id,version)
        return review.detail(teacher,attempt_id)

    @app.post(prefix+'/attempts/{attempt_id}/reports/reviewed/{version}/retry',status_code=202)
    def retry(request:Request,attempt_id:str,version:int,tasks:BackgroundTasks):
        teacher=owner(request,True)
        with service.database.connect() as connection:
            review._owned(connection,teacher,attempt_id); sync.require_complete(connection,attempt_id)
            row=connection.execute('SELECT report_status FROM attempt_conclusions WHERE attempt_id=? AND version=?',(attempt_id,version)).fetchone()
            if not row:
                raise Problem('not_found','Reviewed report not found',404)
        tasks.add_task(reports.generate,teacher,attempt_id,version)
        return {'version':version,'status':row['report_status']}

    @app.get(prefix+'/attempts/{attempt_id}/reports/original')
    def original(request:Request,attempt_id:str):
        return FileResponse(reports.original_file(owner(request),attempt_id),media_type='application/pdf',filename='original-report.pdf')

    @app.get(prefix+'/attempts/{attempt_id}/reports/reviewed/{version}')
    def reviewed(request:Request,attempt_id:str,version:int):
        return FileResponse(reports.reviewed_file(owner(request),attempt_id,version),media_type='application/pdf',filename=f'reviewed-report-v{version}.pdf')

    @app.get(prefix+'/exams/{exam_id}/export.xlsx')
    def spreadsheet(request:Request,exam_id:str):
        return Response(reports.xlsx(owner(request),exam_id),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition':'attachment; filename="exam-attempts.xlsx"'})
