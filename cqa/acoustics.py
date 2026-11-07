"""Local signal measurements. No emotion, speaker identity or silence intention."""
VERSION='signal-v1'


def measure(clip):
    try:
        import numpy as np
        import miniaudio
    except ImportError:
        return {'status':'unavailable','reason':'Установите requirements-audio.txt','version':VERSION}
    audio=miniaudio.decode(clip.data,output_format=miniaudio.SampleFormat.FLOAT32,nchannels=1,sample_rate=16000)
    samples=np.asarray(audio.samples,dtype=np.float32);rate=16000;hop=4000
    if not samples.size or not np.isfinite(samples).all():raise ValueError('Некорректный декодированный сигнал')
    duration=len(samples)/rate
    levels=[];quiet=[];start=None
    for pos in range(0,len(samples),hop):
        block=samples[pos:pos+hop];rms=float(np.sqrt(np.mean(block.astype(np.float64)**2)))
        db=round(20*float(np.log10(max(rms,1e-6))),2);levels.append(db)
        if db < -45 and start is None:start=pos/rate
        if db >= -45 and start is not None:
            if pos/rate-start>=2:quiet.append({'start_seconds':start,'end_seconds':pos/rate})
            start=None
    if start is not None and duration-start>=2:quiet.append({'start_seconds':start,'end_seconds':round(duration,3)})
    pitch={'status':'unavailable'}
    try:
        import parselmouth
        if duration>=.1:
            f0=parselmouth.Sound(samples.astype(np.float64),sampling_frequency=rate).to_pitch_ac(time_step=.02,pitch_floor=75,pitch_ceiling=500).selected_array['frequency']
            voiced=f0[f0>0]
            pitch={'status':'measured' if len(voiced) else 'not_assessable','method':'Praat autocorrelation 75–500 Hz',
                   'median_hz':round(float(np.median(voiced)),1) if len(voiced) else None,
                   'p10_hz':round(float(np.percentile(voiced,10)),1) if len(voiced) else None,
                   'p90_hz':round(float(np.percentile(voiced,90)),1) if len(voiced) else None}
    except ImportError:pass
    except RuntimeError:pitch={'status':'not_assessable'}
    return {'status':'measured','version':VERSION,'audio_sha256':clip.sha256,'duration_seconds':round(duration,3),
            'scope':'whole_channel_including_ivr','window_seconds':.25,'quiet_threshold_dbfs':-45,
            'rms_dbfs':round(20*float(np.log10(max(float(np.sqrt(np.mean(samples.astype(np.float64)**2))),1e-6))),2),
            'near_full_scale_percent':round(float(np.mean(np.abs(samples)>=.999))*100,4),
            'quiet_segments':quiet,'quiet_seconds':round(sum(x['end_seconds']-x['start_seconds'] for x in quiet),3),
            'envelope_dbfs':levels,'pitch':pitch}
