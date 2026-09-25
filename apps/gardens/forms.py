from django import forms
from django.utils import timezone

from .models import (
    GEAR_THRESHOLD,
    FanGearLog,
    Garden,
    Trough,
    WitherBatch,
    garden_gear_ready,
)


class GardenForm(forms.ModelForm):
    class Meta:
        model = Garden
        fields = ["name", "altitudeBand", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input"}),
            "altitudeBand": forms.TextInput(attrs={"class": "input"}),
            "notes": forms.Textarea(attrs={"class": "input", "rows": 3}),
        }


class TroughForm(forms.ModelForm):
    class Meta:
        model = Trough
        fields = ["garden", "troughCode", "cultivar", "loadKg", "status"]
        widgets = {
            "garden": forms.Select(attrs={"class": "input"}),
            "troughCode": forms.TextInput(attrs={"class": "input"}),
            "cultivar": forms.TextInput(attrs={"class": "input"}),
            "loadKg": forms.NumberInput(attrs={"class": "input", "step": "0.01"}),
            "status": forms.Select(attrs={"class": "input"}),
        }


class WitherBatchForm(forms.ModelForm):
    class Meta:
        model = WitherBatch
        fields = [
            "trough",
            "startedAt",
            "targetMoisture",
            "actualMoisture",
            "rollGrade",
        ]
        widgets = {
            "trough": forms.Select(attrs={"class": "input"}),
            "startedAt": forms.DateTimeInput(
                attrs={"class": "input", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "targetMoisture": forms.NumberInput(
                attrs={"class": "input", "step": "0.01"}
            ),
            "actualMoisture": forms.NumberInput(
                attrs={"class": "input", "step": "0.01"}
            ),
            "rollGrade": forms.TextInput(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["startedAt"].input_formats = [
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
        ]
        if self.instance and self.instance.pk and self.instance.startedAt:
            local = timezone.localtime(self.instance.startedAt)
            self.initial["startedAt"] = local.strftime("%Y-%m-%dT%H:%M")

    def clean(self):
        cleaned = super().clean()
        trough = cleaned.get("trough")
        started_at = cleaned.get("startedAt")
        actual = cleaned.get("actualMoisture")
        if actual is None or trough is None or started_at is None:
            return cleaned
        if trough.status == Trough.STATUS_LOADING:
            # 装叶中槽位上的批次不受风机档位门槛限制
            return cleaned
        if not garden_gear_ready(trough.garden, started_at):
            local_start = timezone.localtime(started_at).strftime("%Y-%m-%d %H:%M")
            self.add_error(
                "actualMoisture",
                forms.ValidationError(
                    "茶园「%(garden)s」风机档位未达标：萎凋中/可下槽槽位保存批次"
                    "实测含水率前，须存在该园档位 ≥ %(threshold)s 且切换时刻不早于"
                    "本批次开始（%(start)s）的风机档位切换志。",
                    code="gear_threshold",
                    params={
                        "garden": trough.garden.name,
                        "threshold": GEAR_THRESHOLD,
                        "start": local_start,
                    },
                ),
            )
        return cleaned


class FanGearLogForm(forms.ModelForm):
    class Meta:
        model = FanGearLog
        fields = ["garden", "switchedAt", "gear", "operator", "notes"]
        widgets = {
            "garden": forms.Select(attrs={"class": "input"}),
            "switchedAt": forms.DateTimeInput(
                attrs={"class": "input", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "gear": forms.Select(attrs={"class": "input"}),
            "operator": forms.TextInput(attrs={"class": "input"}),
            "notes": forms.Textarea(attrs={"class": "input", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["switchedAt"].input_formats = [
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
        ]
        if self.instance and self.instance.pk and self.instance.switchedAt:
            local = timezone.localtime(self.instance.switchedAt)
            self.initial["switchedAt"] = local.strftime("%Y-%m-%dT%H:%M")
