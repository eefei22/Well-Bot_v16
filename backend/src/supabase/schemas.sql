-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.context_fact (
  fact_id integer NOT NULL DEFAULT nextval('context_fact_fact_id_seq'::regclass),
  user_id uuid NOT NULL,
  text text NOT NULL,
  tags ARRAY DEFAULT ARRAY[]::text[],
  confidence double precision DEFAULT 0.0,
  recency_days double precision DEFAULT 0.0,
  created_ts timestamp with time zone NOT NULL DEFAULT now(),
  updated_ts timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT context_fact_pkey PRIMARY KEY (fact_id)
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
CREATE TABLE public.guardians (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  email text NOT NULL UNIQUE,
  password text NOT NULL,
  fullname text,
  username text NOT NULL,
  verified boolean DEFAULT false,
  verification_token text,
  token_expires timestamp without time zone,
  token_email text,
  CONSTRAINT guardians_pkey PRIMARY KEY (id)
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
CREATE TABLE public.quotes (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  text text NOT NULL,
  emotion text NOT NULL CHECK (emotion = ANY (ARRAY['happy'::text, 'sad'::text, 'angry'::text, 'fearful'::text])),
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT quotes_pkey PRIMARY KEY (id)
);
CREATE TABLE public.user_context_bundle (
  user_id uuid NOT NULL,
  version_ts timestamp with time zone NOT NULL DEFAULT now(),
  persona_summary text,
  last_session_summary text,
  facts jsonb DEFAULT '[]'::jsonb,
  CONSTRAINT user_context_bundle_pkey PRIMARY KEY (user_id)
);
CREATE TABLE public.users (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  email text NOT NULL UNIQUE,
  password text NOT NULL,
  fullname text NOT NULL,
  username text NOT NULL,
  gender text NOT NULL CHECK (gender = ANY (ARRAY['male'::text, 'female'::text, 'other'::text])),
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
  CONSTRAINT users_pkey PRIMARY KEY (id),
  CONSTRAINT users_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.devices(id)
);
CREATE TABLE public.wb_activity_event (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  type text NOT NULL CHECK (type = ANY (ARRAY['journal'::text, 'gratitude'::text, 'todo'::text, 'meditation'::text, 'quote'::text])),
  ref_id uuid,
  action text NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT wb_activity_event_pkey PRIMARY KEY (id),
  CONSTRAINT wb_activity_event_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);
CREATE TABLE public.wb_conversation (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  started_at timestamp with time zone NOT NULL DEFAULT now(),
  ended_at timestamp with time zone,
  reason_ended text,
  CONSTRAINT wb_conversation_pkey PRIMARY KEY (id),
  CONSTRAINT wb_conversation_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
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
  CONSTRAINT wb_embeddings_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);
CREATE TABLE public.wb_gratitude_item (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  text text NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT wb_gratitude_item_pkey PRIMARY KEY (id),
  CONSTRAINT wb_gratitude_item_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);
CREATE TABLE public.wb_journal (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  title text NOT NULL,
  body text NOT NULL,
  mood integer NOT NULL CHECK (mood >= 1 AND mood <= 5),
  topics ARRAY NOT NULL DEFAULT '{}'::text[],
  is_draft boolean NOT NULL DEFAULT false,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT wb_journal_pkey PRIMARY KEY (id),
  CONSTRAINT wb_journal_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.wb_meditation_log (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  video_id uuid,
  started_at timestamp with time zone NOT NULL,
  ended_at timestamp with time zone,
  outcome USER-DEFINED NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT wb_meditation_log_pkey PRIMARY KEY (id),
  CONSTRAINT wb_meditation_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id),
  CONSTRAINT wb_meditation_log_video_id_fkey FOREIGN KEY (video_id) REFERENCES public.wb_meditation_video(id)
);
CREATE TABLE public.wb_meditation_video (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  uri text NOT NULL,
  label text NOT NULL,
  active boolean NOT NULL DEFAULT true,
  provider USER-DEFINED NOT NULL DEFAULT 'supabase'::meditation_provider_enum,
  youtube_id text,
  duration_seconds integer,
  CONSTRAINT wb_meditation_video_pkey PRIMARY KEY (id)
);
CREATE TABLE public.wb_message (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL,
  role text NOT NULL CHECK (role = ANY (ARRAY['user'::text, 'assistant'::text])),
  text text NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  tsv tsvector DEFAULT to_tsvector('english'::regconfig, COALESCE(text, ''::text)),
  tokens integer,
  metadata jsonb DEFAULT '{}'::jsonb,
  CONSTRAINT wb_message_pkey PRIMARY KEY (id),
  CONSTRAINT wb_message_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.wb_conversation(id)
);
CREATE TABLE public.wb_preferences (
  user_id uuid NOT NULL,
  language text NOT NULL DEFAULT 'en'::text,
  religion USER-DEFINED,
  flags jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT wb_preferences_pkey PRIMARY KEY (user_id),
  CONSTRAINT wb_preferences_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);
CREATE TABLE public.wb_quote (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  category USER-DEFINED NOT NULL,
  text text NOT NULL,
  language text NOT NULL DEFAULT 'en'::text,
  CONSTRAINT wb_quote_pkey PRIMARY KEY (id)
);
CREATE TABLE public.wb_quote_seen (
  user_id uuid NOT NULL,
  quote_id uuid NOT NULL,
  seen_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT wb_quote_seen_pkey PRIMARY KEY (user_id, quote_id),
  CONSTRAINT wb_quote_seen_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id),
  CONSTRAINT wb_quote_seen_quote_id_fkey FOREIGN KEY (quote_id) REFERENCES public.wb_quote(id)
);
CREATE TABLE public.wb_safety_event (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  session_id uuid,
  ts timestamp with time zone NOT NULL DEFAULT now(),
  lang text,
  action_taken text,
  user_acknowledged boolean,
  redacted_phrase text,
  severity text CHECK (severity = ANY (ARRAY['SI_INTENT'::text, 'SI_IDEATION'::text, 'SELF_HARM'::text])),
  CONSTRAINT wb_safety_event_pkey PRIMARY KEY (id)
);
CREATE TABLE public.wb_session_log (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  started_at timestamp with time zone NOT NULL DEFAULT now(),
  ended_at timestamp with time zone,
  reason_ended text CHECK (reason_ended = ANY (ARRAY['manual'::text, 'inactivity'::text])),
  avg_latency_ms integer,
  asr_wer_estimate numeric,
  CONSTRAINT wb_session_log_pkey PRIMARY KEY (id),
  CONSTRAINT wb_session_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);
CREATE TABLE public.wb_todo_item (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  title text NOT NULL,
  status USER-DEFINED NOT NULL DEFAULT 'open'::todo_status_enum,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  completed_at timestamp with time zone,
  CONSTRAINT wb_todo_item_pkey PRIMARY KEY (id),
  CONSTRAINT wb_todo_item_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);
CREATE TABLE public.wb_tool_invocation_log (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  session_id uuid,
  tool text NOT NULL,
  status text NOT NULL CHECK (status = ANY (ARRAY['ok'::text, 'error'::text])),
  duration_ms integer,
  error_code text,
  payload_size integer,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT wb_tool_invocation_log_pkey PRIMARY KEY (id)
);