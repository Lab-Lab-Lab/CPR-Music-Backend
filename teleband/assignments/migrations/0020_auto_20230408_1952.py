# Generated by Django 3.2.11 on 2023-04-08 23:52

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('musics', '0018_seed_more_music'),
        ('courses', '0005_data_migration_demo_course'),
        ('assignments', '0019_add_connect'),
    ]

    operations = [
        migrations.CreateModel(
            name='Curriculum',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('course', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='courses.course')),
            ],
        ),
        migrations.CreateModel(
            name='PiecePlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('ordered', models.BooleanField(default=False)),
            ],
        ),
        migrations.CreateModel(
            name='PiecePlanActivity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order', models.PositiveIntegerField()),
                ('activity', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='assignments.activity')),
                ('piece_plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='assignments.pieceplan')),
            ],
            options={
                'ordering': ['order'],
                'unique_together': {('piece_plan', 'activity')},
            },
        ),
        migrations.AddField(
            model_name='pieceplan',
            name='activities',
            field=models.ManyToManyField(through='assignments.PiecePlanActivity', to='assignments.Activity'),
        ),
        migrations.AddField(
            model_name='pieceplan',
            name='piece',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='musics.piece'),
        ),
        migrations.CreateModel(
            name='CurriculumPiecePlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order', models.PositiveIntegerField()),
                ('curriculum', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='assignments.curriculum')),
                ('piece_plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='assignments.pieceplan')),
            ],
            options={
                'ordering': ['order'],
                'unique_together': {('curriculum', 'piece_plan')},
            },
        ),
        migrations.AddField(
            model_name='curriculum',
            name='piece_plans',
            field=models.ManyToManyField(through='assignments.CurriculumPiecePlan', to='assignments.PiecePlan'),
        ),
    ]