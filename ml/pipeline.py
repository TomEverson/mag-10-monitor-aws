import os

import boto3
import sagemaker
from sagemaker.processing import ProcessingInput, ProcessingOutput
from sagemaker.sklearn.estimator import SKLearn
from sagemaker.sklearn.processing import SKLearnProcessor
from sagemaker.workflow.condition_step import ConditionStep
from sagemaker.workflow.conditions import (
    ConditionAnd,
    ConditionGreaterThanOrEqualTo,
    ConditionLessThanOrEqualTo,
)
from sagemaker.workflow.fail_step import FailStep
from sagemaker.workflow.functions import JsonGet
from sagemaker.workflow.model_step import ModelStep
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.pipeline_context import PipelineSession
from sagemaker.workflow.properties import PropertyFile
from sagemaker.workflow.steps import ProcessingStep, TrainingStep

PIPELINE_NAME    = "mag10-training-pipeline"
MODEL_GROUP      = "mag10-anomaly-detector"
BUCKET           = os.environ.get("S3_BUCKET", "mag10-data-prod")
ROLE             = os.environ.get("SAGEMAKER_ROLE_ARN")
REGION           = os.environ.get("AWS_REGION", "us-east-1")
SKLEARN_VERSION  = "1.2-1"


def build_pipeline() -> Pipeline:
    session = PipelineSession()

    # ------------------------------------------------------------------
    # Step 1 — Feature engineering (Processing Job)
    # ------------------------------------------------------------------
    fe_processor = SKLearnProcessor(
        framework_version=SKLEARN_VERSION,
        instance_type="ml.t3.medium",
        instance_count=1,
        role=ROLE,
        sagemaker_session=session,
    )

    step_fe = ProcessingStep(
        name="feature-engineering",
        processor=fe_processor,
        inputs=[
            ProcessingInput(
                source=f"s3://{BUCKET}/bronze/",
                destination="/opt/ml/processing/input",
            )
        ],
        outputs=[
            ProcessingOutput(
                output_name="train",
                source="/opt/ml/processing/output/train",
                destination=f"s3://{BUCKET}/features/train",
            ),
            ProcessingOutput(
                output_name="validation",
                source="/opt/ml/processing/output/validation",
                destination=f"s3://{BUCKET}/features/validation",
            ),
        ],
        code="ml/preprocessing/feature_engineering.py",
    )

    # ------------------------------------------------------------------
    # Step 2 — Training Job
    # ------------------------------------------------------------------
    estimator = SKLearn(
        entry_point="train.py",
        source_dir="ml/training",
        framework_version=SKLEARN_VERSION,
        instance_type="ml.m5.large",
        instance_count=1,
        role=ROLE,
        sagemaker_session=session,
        hyperparameters={
            "n_estimators":  200,
            "contamination": 0.1,
            "random_state":  42,
        },
        output_path=f"s3://{BUCKET}/models/",
    )

    step_train = TrainingStep(
        name="train-isolation-forest",
        estimator=estimator,
        inputs={
            "train": sagemaker.inputs.TrainingInput(
                s3_data=step_fe.properties.ProcessingOutputConfig.Outputs["train"].S3Output.S3Uri,
            )
        },
    )

    # ------------------------------------------------------------------
    # Step 3 — Evaluation (Processing Job)
    # ------------------------------------------------------------------
    eval_processor = SKLearnProcessor(
        framework_version=SKLEARN_VERSION,
        instance_type="ml.t3.medium",
        instance_count=1,
        role=ROLE,
        sagemaker_session=session,
    )

    evaluation_report = PropertyFile(
        name="evaluation-report",
        output_name="evaluation",
        path="evaluation.json",
    )

    step_eval = ProcessingStep(
        name="evaluate-model",
        processor=eval_processor,
        inputs=[
            ProcessingInput(
                source=step_train.properties.ModelArtifacts.S3ModelArtifacts,
                destination="/opt/ml/processing/model",
            ),
            ProcessingInput(
                source=step_fe.properties.ProcessingOutputConfig.Outputs["validation"].S3Output.S3Uri,
                destination="/opt/ml/processing/input",
            ),
        ],
        outputs=[
            ProcessingOutput(
                output_name="evaluation",
                source="/opt/ml/processing/output",
                destination=f"s3://{BUCKET}/evaluations/",
            )
        ],
        code="ml/evaluation/evaluate.py",
        property_files=[evaluation_report],
    )

    # ------------------------------------------------------------------
    # Step 4 — ConditionStep: 0.03 <= anomaly_rate <= 0.20
    # ------------------------------------------------------------------
    anomaly_rate = JsonGet(
        step_name=step_eval.name,
        property_file=evaluation_report,
        json_path="anomaly_rate",
    )

    cond_pass = ConditionAnd(conditions=[
        ConditionGreaterThanOrEqualTo(left=anomaly_rate, right=0.03),
        ConditionLessThanOrEqualTo(left=anomaly_rate, right=0.20),
    ])

    # ------------------------------------------------------------------
    # Step 5 — RegisterModel
    # ------------------------------------------------------------------
    from sagemaker.sklearn.model import SKLearnModel

    model = SKLearnModel(
        model_data=step_train.properties.ModelArtifacts.S3ModelArtifacts,
        role=ROLE,
        entry_point="inference.py",
        source_dir="ml/inference",
        framework_version=SKLEARN_VERSION,
        sagemaker_session=session,
    )

    step_register = ModelStep(
        name="register-model",
        step_args=model.register(
            content_types=["application/json"],
            response_types=["application/json"],
            inference_instances=["ml.t3.medium"],
            transform_instances=["ml.m5.large"],
            model_package_group_name=MODEL_GROUP,
            approval_status="PendingManualApproval",
            model_metrics=sagemaker.model_metrics.ModelMetrics(
                model_statistics=sagemaker.model_metrics.MetricsSource(
                    s3_uri=f"{step_eval.properties.ProcessingOutputConfig.Outputs['evaluation'].S3Output.S3Uri}/evaluation.json",
                    content_type="application/json",
                )
            ),
        ),
    )

    step_fail = FailStep(
        name="anomaly-rate-out-of-range",
        error_message=f"Anomaly rate outside [0.03, 0.20]. Pipeline halted.",
    )

    step_condition = ConditionStep(
        name="check-anomaly-rate",
        conditions=[cond_pass],
        if_steps=[step_register],
        else_steps=[step_fail],
    )

    # ------------------------------------------------------------------
    # Assemble pipeline
    # ------------------------------------------------------------------
    return Pipeline(
        name=PIPELINE_NAME,
        steps=[step_fe, step_train, step_eval, step_condition],
        sagemaker_session=session,
    )


if __name__ == "__main__":
    pipeline = build_pipeline()
    pipeline.upsert(role_arn=ROLE)
    print(f"Pipeline '{PIPELINE_NAME}' upserted.")
