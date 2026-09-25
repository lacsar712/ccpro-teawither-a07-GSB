from django import forms

from .models import FanGearLog, Garden, Trough, WitherBatch


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
            from django.utils import timezone

            local = timezone.localtime(self.instance.startedAt)
            self.initial["startedAt"] = local.strftime("%Y-%m-%dT%H:%M")

    def clean(self):
        cleaned = super().clean()
        trough = cleaned.get("trough")
        started_at = cleaned.get("startedAt")
        actual = cleaned.get("actualMoisture")

        # 仅当本次要写入（非空）实测含水率时才设门槛
        if trough is None or started_at is None or actual is None:
            return cleaned

        # 装叶中槽上的批次不受风机档位门槛限制
        if trough.status == Trough.STATUS_LOADING:
            return cleaned

        # 萎凋中、可下槽槽位：须有该园最近一次达到约定档位（≥3 档）
        # 的切换志，且切换时刻不早于本批次开始
        if trough.garden.gear_covers_batch(started_at):
            return cleaned

        latest = trough.garden.latest_gear_log()
        if latest is None:
            reason = "该园尚无风机档位切换志"
        elif latest.gear < FanGearLog.GEAR_THRESHOLD:
            reason = f"该园最近一次风机档位仅为 {latest.gear} 档（需 ≥ {FanGearLog.GEAR_THRESHOLD} 档）"
        else:
            reason = (
                f"该园最近一次达标切换时刻为 {latest.switchedAt:%Y-%m-%d %H:%M}，"
                f"早于本批次开始时间 {started_at:%Y-%m-%d %H:%M}"
            )
        raise forms.ValidationError(
            f"无法保存实测含水率：{reason}。请先在「风机档位」中登记不早于批次开始时间的"
            f" {FanGearLog.GEAR_THRESHOLD} 档及以上切换记录（装叶中槽位除外）。"
        )


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
            from django.utils import timezone

            local = timezone.localtime(self.instance.switchedAt)
            self.initial["switchedAt"] = local.strftime("%Y-%m-%dT%H:%M")
        else:
            from django.utils import timezone

            local = timezone.localtime(timezone.now())
            self.initial["switchedAt"] = local.strftime("%Y-%m-%dT%H:%M")
            self.initial["gear"] = FanGearLog.GEAR_THRESHOLD
