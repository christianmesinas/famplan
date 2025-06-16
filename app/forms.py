from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, TextAreaField, SelectField
from wtforms.validators import ValidationError, DataRequired, Length
import sqlalchemy as sa
from app import db
from app.models import User
from flask_wtf.file import FileField, FileAllowed


# Formulier om het profiel van een gebruiker te bewerken
class EditProfileForm(FlaskForm):
    # Veld voor de gebruikersnaam, verplicht om in te vullen
    username = StringField('Username', validators=[DataRequired()])
    about_me = TextAreaField('About me',
                             validators=[Length(min=0, max=140)])
    submit = SubmitField('Submit')
    profile_picture = FileField('Profielfoto', validators=[
        FileAllowed(['jpg', 'jpeg', 'png'], 'Alleen afbeeldingen zijn toegestaan!')])


    def __init__(self, original_username, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_username = original_username

    # Constructor om de oorspronkelijke gebruikersnaam op te slaan
    def validate_username(self, username):
        if username.data != self.original_username:
            user = db.session.scalar(sa.select(User).where(
                User.username == username.data))
            if user is not None:
                raise ValidationError('Please use a different username.')

# Een leeg formulier met alleen een submit-knop
class EmptyForm(FlaskForm):
    submit = SubmitField('Submit')

# Formulier om een nieuwe post te maken
class PostForm(FlaskForm):
    post = TextAreaField('Say something', validators=[
        DataRequired(), Length(min=1, max=520)])
    family = SelectField('Post to Family', coerce=int)
    submit = SubmitField('Submit')

# Formulier om een privébericht te sturen
class MessageForm(FlaskForm):
    message = TextAreaField('Message', validators=[
        DataRequired(), Length(min=1, max=520)])
    submit = SubmitField('Submit')

# -----------------------------------------------
# Family stuff ahead
# -----------------------------------------------
class FamilyForm(FlaskForm):
    """Form to create a new Family."""
    name = StringField(
        'Family name',
        validators=[DataRequired(), Length(min=3, max=64)]
    )
    submit = SubmitField('Create Family')

class InviteForm(FlaskForm):
    """Form to generate (or re-generate) an invite token."""
    invited_email = StringField(
        'Invite email (optional)',
        validators=[Length(max=120)]
    )
    submit = SubmitField('Generate Invite')

class JoinForm(FlaskForm):
    """Form where a user enters a token to join a Family."""
    token = StringField(
        'Join token',
        validators=[DataRequired(), Length(min=8, max=64)]
    )
    submit = SubmitField('Join Family')

class EditFamilyForm(FlaskForm):
    """Form to edit a Family."""
    name = StringField('Family name', validators=[DataRequired(), Length(1, 64)])
    rename = SubmitField('Save')