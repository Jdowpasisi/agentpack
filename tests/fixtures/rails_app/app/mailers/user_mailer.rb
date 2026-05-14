class UserMailer
  def welcome_email(user)
    "welcome #{user.email}"
  end

  def password_reset(user)
    "reset #{user.email}"
  end
end
