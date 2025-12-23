-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.bvs_emotion (
  id bigint NOT NULL DEFAULT nextval('bvs_emotion_id_seq'::regclass),
  user_id uuid NOT NULL,
  timestamp timestamp with time zone NOT NULL,
  predicted_emotion character varying CHECK (predicted_emotion IS NULL OR (predicted_emotion::text = ANY (ARRAY['Happy'::character varying, 'Sad'::character varying, 'Angry'::character varying, 'Fear'::character varying]::text[]))),
  emotion_confidence double precision CHECK (emotion_confidence >= 0::double precision AND emotion_confidence <= 1::double precision),
  date date DEFAULT CURRENT_DATE,
  CONSTRAINT bvs_emotion_pkey PRIMARY KEY (id),
  CONSTRAINT bvs_emotion_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.daily_emotion_aggregates (
  user_id uuid NOT NULL,
  day date NOT NULL,
  emotion_label character varying NOT NULL,
  cnt bigint NOT NULL DEFAULT 0,
  total_conf numeric NOT NULL DEFAULT 0,
  total_emotional numeric NOT NULL DEFAULT 0,
  CONSTRAINT daily_emotion_aggregates_pkey PRIMARY KEY (user_id, day, emotion_label)
);
CREATE TABLE public.devices (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  serial_number text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'inactive'::text CHECK (status = ANY (ARRAY['active'::text, 'inactive'::text])),
  fitbit_access_token text NOT NULL,
  fitbit_refresh_token text NOT NULL,
  fitbit_expires_at timestamp without time zone NOT NULL,
  CONSTRAINT devices_pkey PRIMARY KEY (id)
);
CREATE TABLE public.emotional_log (
  id integer NOT NULL DEFAULT nextval('emotional_log_id_seq'::regclass),
  user_id uuid NOT NULL,
  timestamp timestamp without time zone NOT NULL,
  emotion_label character varying NOT NULL CHECK (emotion_label::text = ANY (ARRAY['Angry'::character varying::text, 'Sad'::character varying::text, 'Happy'::character varying::text, 'Fear'::character varying::text])),
  confidence_score real NOT NULL CHECK (confidence_score >= 0::double precision AND confidence_score <= 1::double precision),
  emotional_score integer CHECK (emotional_score >= 0 AND emotional_score <= 100),
  CONSTRAINT emotional_log_pkey PRIMARY KEY (id),
  CONSTRAINT emotional_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.face_emotion (
  id integer NOT NULL DEFAULT nextval('face_emotions_id_seq'::regclass),
  user_id uuid NOT NULL,
  timestamp timestamp without time zone NOT NULL,
  predicted_emotion character varying NOT NULL,
  emotion_confidence double precision NOT NULL,
  date date DEFAULT CURRENT_DATE,
  CONSTRAINT face_emotion_pkey PRIMARY KEY (id),
  CONSTRAINT face_emotions_user_id_fkey1 FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.guardians (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  email text NOT NULL UNIQUE,
  password text NOT NULL,
  full_name text,
  prefer_name text NOT NULL,
  verified boolean DEFAULT false,
  verification_token text,
  token_expires timestamp without time zone,
  token_email text,
  CONSTRAINT guardians_pkey PRIMARY KEY (id)
);
CREATE TABLE public.intervention_log (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  public_id uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  user_id uuid NOT NULL,
  emotional_log_id bigint,
  intervention_type character varying NOT NULL CHECK (intervention_type::text = ANY (ARRAY['Support Chat'::character varying, 'Journaling'::character varying, 'Meditation with Music'::character varying, 'Breathing Exercise'::character varying, 'Gratitude'::character varying, 'Daily Quote'::character varying]::text[])),
  timestamp timestamp without time zone NOT NULL,
  mood_rating ARRAY,
  end_timestamp timestamp without time zone,
  duration interval DEFAULT (end_timestamp - "timestamp"),
  CONSTRAINT intervention_log_pkey PRIMARY KEY (id),
  CONSTRAINT intervention_log_emotional_log_id_fkey FOREIGN KEY (emotional_log_id) REFERENCES public.emotional_log(id),
  CONSTRAINT intervention_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.music_emotion (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  user_id uuid NOT NULL,
  timestamp timestamp with time zone,
  predicted_emotion text,
  emotion_confidence double precision,
  date date DEFAULT CURRENT_DATE,
  CONSTRAINT music_emotion_pkey PRIMARY KEY (id),
  CONSTRAINT music_emotions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.permissions (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  guardian_id uuid,
  user_id uuid,
  status text CHECK (status = ANY (ARRAY['active'::text, 'pending'::text, 'reject'::text, 'revoked'::text])),
  requested_at timestamp without time zone,
  updated_at timestamp without time zone,
  request_message text,
  CONSTRAINT permissions_pkey PRIMARY KEY (id),
  CONSTRAINT permissions_guardian_id_fkey FOREIGN KEY (guardian_id) REFERENCES public.guardians(id),
  CONSTRAINT permissions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.users (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  email text NOT NULL UNIQUE,
  password text NOT NULL,
  full_name text NOT NULL,
  gender text NOT NULL CHECK (gender = ANY (ARRAY['Male'::text, 'Female'::text])),
  age integer NOT NULL CHECK (age >= 0),
  language text NOT NULL,
  cultural_background text NOT NULL,
  spiritual_beliefs text NOT NULL,
  device_id uuid,
  allow_guardian boolean DEFAULT false,
  verified boolean DEFAULT false,
  verification_token text,
  token_expires timestamp without time zone,
  token_email text,
  prefer_intervention jsonb NOT NULL DEFAULT '{"plan": true, "music": true, "quote": true, "converse": true, "breathing": true, "gratitude": true, "journaling": true}'::jsonb,
  prefer_name text,
  CONSTRAINT users_pkey PRIMARY KEY (id),
  CONSTRAINT users_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.devices(id)
);
CREATE TABLE public.users_context_bundle (
  user_id uuid NOT NULL,
  version_ts timestamp with time zone NOT NULL DEFAULT now(),
  persona_summary text,
  last_session_summary text,
  facts text,
  CONSTRAINT users_context_bundle_pkey PRIMARY KEY (user_id)
);
CREATE TABLE public.voice_emotion (
  frame_id integer NOT NULL DEFAULT nextval('voice_emotion_frame_id_seq'::regclass),
  user_id uuid,
  timestamp timestamp without time zone NOT NULL,
  sample_rate integer NOT NULL,
  frame_size_ms double precision NOT NULL,
  frame_stride_ms double precision NOT NULL,
  duration_sec double precision NOT NULL,
  pitch_mean double precision,
  pitch_std double precision,
  energy_mean double precision,
  energy_std double precision,
  speech_rate double precision,
  mfcc_vector ARRAY,
  chroma_vector ARRAY,
  spectral_centroid double precision,
  spectral_bandwidth double precision,
  spectral_rolloff double precision,
  zero_crossing_rate double precision,
  formants ARRAY,
  jitter double precision,
  shimmer double precision,
  harmonics_to_noise_ratio double precision,
  predicted_emotion character varying,
  emotion_confidence double precision,
  transcript text,
  language character varying,
  sentiment character varying,
  sentiment_confidence double precision,
  CONSTRAINT voice_emotion_pkey PRIMARY KEY (frame_id),
  CONSTRAINT voice_emotion_analysis_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.wb_conversation (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  started_at timestamp with time zone NOT NULL DEFAULT now(),
  ended_at timestamp with time zone,
  reason_ended text,
  CONSTRAINT wb_conversation_pkey PRIMARY KEY (id),
  CONSTRAINT wb_conversation_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.wb_embeddings (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  kind text NOT NULL CHECK (kind = ANY (ARRAY['message'::text, 'journal'::text, 'todo'::text, 'preference'::text, 'gratitude'::text])),
  ref_id uuid NOT NULL,
  vector USER-DEFINED NOT NULL,
  model_tag text NOT NULL CHECK (model_tag = ANY (ARRAY['miniLM'::text, 'e5'::text])),
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT wb_embeddings_pkey PRIMARY KEY (id),
  CONSTRAINT wb_embeddings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.wb_gratitude_item (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  text text NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone,
  fav boolean NOT NULL DEFAULT false,
  CONSTRAINT wb_gratitude_item_pkey PRIMARY KEY (id),
  CONSTRAINT wb_gratitude_item_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.wb_journal (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  title text NOT NULL,
  body text NOT NULL,
  mood integer CHECK (mood >= 1 AND mood <= 5),
  topics ARRAY NOT NULL DEFAULT '{}'::text[],
  is_draft boolean NOT NULL DEFAULT false,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  fav boolean NOT NULL DEFAULT false,
  CONSTRAINT wb_journal_pkey PRIMARY KEY (id),
  CONSTRAINT wb_journal_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.wb_message (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL,
  role text NOT NULL CHECK (role = ANY (ARRAY['user'::text, 'assistant'::text])),
  text text NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  tokens integer,
  metadata jsonb DEFAULT '{}'::jsonb,
  CONSTRAINT wb_message_pkey PRIMARY KEY (id),
  CONSTRAINT wb_message_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.wb_conversation(id)
);
CREATE TABLE public.wb_quote (
  id text NOT NULL DEFAULT gen_random_uuid(),
  category text NOT NULL CHECK (category = ANY (ARRAY['general'::text, 'christian'::text, 'islamic'::text, 'buddhist'::text, 'hindu'::text])),
  text text NOT NULL,
  language text NOT NULL DEFAULT 'en'::text,
  CONSTRAINT wb_quote_pkey PRIMARY KEY (id)
);
CREATE TABLE public.wb_quote_seen (
  user_id uuid NOT NULL,
  quote_id text NOT NULL,
  seen_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT wb_quote_seen_pkey PRIMARY KEY (user_id, quote_id),
  CONSTRAINT wb_quote_seen_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id),
  CONSTRAINT wb_quote_seen_quote_id_fkey FOREIGN KEY (quote_id) REFERENCES public.wb_quote(id)
);
CREATE TABLE public.z_meditation_video (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  uri text NOT NULL,
  label text NOT NULL,
  active boolean NOT NULL DEFAULT true,
  provider text NOT NULL DEFAULT 'supabase'::text CHECK (provider = ANY (ARRAY['youtube'::text, 'supabase'::text])),
  youtube_id text,
  duration_seconds integer,
  CONSTRAINT z_meditation_video_pkey PRIMARY KEY (id)
);
CREATE TABLE public.z_migration_combined_backup (
  id uuid DEFAULT gen_random_uuid(),
  origin_schema text,
  origin_table text,
  origin_pk jsonb,
  row_data jsonb,
  inserted_at timestamp with time zone DEFAULT now()
);