class EmailJob
  def perform(user)
    UserMailer.new.welcome_email(user)
  end
end
